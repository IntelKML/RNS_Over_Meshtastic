# Unified Meshtastic Interface for Reticulum
# --------------------------------------------------
# Supports both Android TCP Bridge mode and native (serial/ble/tcp) Meshtastic device modes
# Used for bridging Reticulum over Meshtastic (RNS over mesh)

import RNS
import struct
import threading
import time
import re
import base64
import socket
import sys
from RNS.Interfaces.Interface import Interface

# Allow importing Meshtastic modules if installed in user-local path
sys.path.insert(0, r"C:\\Users\\Admin\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages")

class MeshtasticInterface(Interface):
    # Mapping between Meshtastic speed levels and artificial delays (unused but available for future throttling)
    speed_to_delay = {8: .4, 6: 1, 5: 3, 7: 12, 4: 4, 3: 6, 1: 15, 0: 8}

    DEFAULT_IFAC_SIZE = 8
    _META_FMT = struct.Struct("Bb")  # Struct to pack/unpack message index and fragment position
    MIN_RNS_FRAME = 16  # Smallest valid RNS frame

    def __init__(self, owner, configuration):
        # Ensure meshtastic module is available
        import importlib.util
        if importlib.util.find_spec('meshtastic') is None:
            RNS.log("Install meshtastic via pip for this interface", RNS.LOG_CRITICAL)
            RNS.panic()

        import meshtastic
        from pubsub import pub

        self.mt_bin_port = meshtastic.portnums_pb2.RETICULUM_TUNNEL_APP

        # Load configuration and initialize common fields
        super().__init__()
        ifconf = Interface.get_config_obj(configuration)

        self.name = ifconf.get("name", "Meshtastic")
        self.port = ifconf.get("port")
        self.ble_port = ifconf.get("ble_port")
        self.tcp_port = ifconf.get("tcp_port")
        self.android_host = ifconf.get("android_tcp_host")
        self.android_port = int(ifconf.get("android_tcp_port", 4403))
        self.speed = int(ifconf.get("data_speed", 8))
        self.hop_limit = int(ifconf.get("hop_limit", 1))
        self.bitrate = int(ifconf.get("bitrate", 500))
        self.HW_MTU = 564

        self.owner = owner
        self.online = False
        self._sock = None
        self._tx_lock = threading.Lock()
        self._stop = threading.Event()

        # Outgoing and reassembly logic for multi-packet fragmentation
        self.packet_index = 0
        self.packet_i_queue = []
        self.outgoing_packet_storage = {}
        self.assembly_dict = {}
        self.expected_index = {}
        self.requested_index = {}
        self.dest_to_node_dict = {}

        # Determine connection mode
        if self.port or self.ble_port or self.tcp_port:
            self.mode = "native"
        elif self.android_host:
            self.mode = "android"
        else:
            raise ValueError("No valid mode configured for Meshtastic_Interface")

        RNS.log(f"[Meshtastic] Interface '{self.name}' mode={self.mode} loaded", RNS.LOG_NOTICE)

        if self.mode == "native":
            self._init_native()
        else:
            self._init_android()

    # Initialize native interface (Serial, BLE, or TCP)
    def _init_native(self):
        import meshtastic
        from pubsub import pub

        if self.port:
            from meshtastic.serial_interface import SerialInterface
            self.interface = SerialInterface(devPath=self.port)
        elif self.ble_port:
            from meshtastic.ble_interface import BLEInterface
            self.interface = BLEInterface(address=self.ble_port)
        elif self.tcp_port:
            from meshtastic.tcp_interface import TCPInterface, DEFAULT_TCP_PORT
            host, port = self.tcp_port.split(":") if ":" in self.tcp_port else (self.tcp_port, DEFAULT_TCP_PORT)
            self.interface = TCPInterface(hostname=host, portNumber=int(port))

        # Register message handlers
        pub.subscribe(self._process_message_native, "meshtastic.receive")
        pub.subscribe(self._native_connected, "meshtastic.connection.established")
        pub.subscribe(self._native_closed, "meshtastic.connection.lost")

    # Initialize Android TCP bridge mode
    def _init_android(self):
        threading.Thread(target=self._connector_loop, daemon=True).start()

    def _native_connected(self, iface):
        self.online = True
        RNS.log("[Meshtastic] Native connected", RNS.LOG_NOTICE)

    def _native_closed(self, iface):
        self.online = False
        RNS.log("[Meshtastic] Native disconnected", RNS.LOG_WARNING)

    def _process_message_native(self, packet, iface):
        # Handle incoming Meshtastic packet if it's for Reticulum tunnel
        dec = packet.get("decoded")
        if not dec or dec.get("portnum") != "RETICULUM_TUNNEL_APP":
            return
        payload = dec.get("payload")
        if payload and len(payload) >= self.MIN_RNS_FRAME:
            self.rxb += len(payload)
            self.owner.inbound(payload, self)

    # Main connector loop for Android TCP bridge
    def _connector_loop(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                s = socket.create_connection((self.android_host, self.android_port))
                self._sock = s
                self.online = True
                backoff = 1.0
                RNS.log(f"[Meshtastic] Connected to Android TCP bridge", RNS.LOG_NOTICE)

                f = s.makefile("rb")
                while not self._stop.is_set():
                    line = f.readline()
                    if not line:
                        raise ConnectionError("Socket closed")
                    line = line.strip()
                    if not line or not self._looks_like_b64(line):
                        continue
                    try:
                        chunk = base64.b64decode(line, validate=True)
                        if len(chunk) < self._META_FMT.size + 1:
                            continue
                        idx, pos = self._META_FMT.unpack(chunk[:self._META_FMT.size])
                        from_id = "tcppeer"
                        handlers = self.assembly_dict.setdefault(from_id, {})
                        handler = handlers.setdefault(idx, PacketHandler(index=idx))
                        data = handler.process_packet(chunk)
                        self.rxb += len(chunk)
                        if data and len(data) >= self.MIN_RNS_FRAME:
                            self.owner.inbound(data, self)
                            del handlers[idx]
                    except Exception:
                        continue
            except Exception as e:
                RNS.log(f"[Meshtastic] TCP error: {e}", RNS.LOG_ERROR)
                self._teardown_socket()
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # Simple heuristic to validate base64 format
    def _looks_like_b64(self, bline: bytes) -> bool:
        return len(bline) % 4 == 0 and re.fullmatch(rb"[A-Za-z0-9+/]+={0,2}", bline) is not None

    def _teardown_socket(self):
        self.online = False
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    # Handle outgoing messages from Reticulum
    def process_outgoing(self, data: bytes):
        if self.mode == "native":
            try:
                self.interface.sendData(
                    data,
                    portNum=self.mt_bin_port,
                    destinationId="^all",
                    wantAck=False,
                    wantResponse=False,
                    channelIndex=0,
                    hopLimit=self.hop_limit,
                )
                self.txb += len(data)
            except Exception as e:
                RNS.log(f"[Meshtastic] Native TX error: {e}", RNS.LOG_ERROR)
            return

        # Android TCP bridge mode
        if not self.online or not self._sock:
            RNS.log("[Meshtastic] TX dropped (not connected)", RNS.LOG_WARNING)
            return
        try:
            handler = PacketHandler(data, self.packet_index)
            self.outgoing_packet_storage[self.packet_index] = handler
            for pos in handler.get_keys():
                frag = handler[pos]
                line = base64.b64encode(frag) + b"\n"
                with self._tx_lock:
                    self._sock.sendall(line)
            self.packet_index = (self.packet_index + 1) % 256
            self.txb += len(data)
        except Exception as e:
            RNS.log(f"[Meshtastic] TX error: {e}", RNS.LOG_ERROR)
            self._teardown_socket()

    @staticmethod
    def should_ingress_limit():
        return False

    def __str__(self):
        return f"MeshtasticInterface[{self.name}]"

# PacketHandler handles chunking and reassembly of fragmented RNS packets
class PacketHandler:
    _FMT = struct.Struct("Bb")  # Index, position

    def __init__(self, data=None, index=None, max_payload=200):
        self.index = index if index is not None else 0
        self.max_payload = max_payload
        self.data_dict = {}  # Fragment buffer
        if data:
            self._split(data)

    def _split(self, data):
        total = len(data)
        chunks = [data[i:i + self.max_payload] for i in range(0, total, self.max_payload)]
        for i, chunk in enumerate(chunks, 1):
            pos = -i if i == len(chunks) else i
            self.data_dict[abs(pos)] = self._FMT.pack(self.index, pos) + chunk

    def get_keys(self):
        return self.data_dict.keys()

    def __getitem__(self, i):
        return self.data_dict.get(i)

    def process_packet(self, fragment: bytes):
        if len(fragment) < self._FMT.size + 1:
            return None
        idx, pos = self._FMT.unpack(fragment[:self._FMT.size])
        self.index = idx
        self.data_dict[abs(pos)] = fragment
        if pos < 0:
            return self._assemble()
        return None

    def _assemble(self):
        keys = sorted(self.data_dict.keys())
        if keys != list(range(1, keys[-1] + 1)):
            return None
        return b"".join(self.data_dict[k][self._FMT.size:] for k in keys)

def calc_index(i):
    return (i + 1) % 256

# Required export for Reticulum interface loader
interface_class = MeshtasticInterface
