# MIT License - Copyright (c) 2024 Mark Qvist / unsigned.io

# This example illustrates creating a custom interface
# definition, that can be loaded and used by Reticulum at
# runtime. Any number of custom interfaces can be created
# and loaded. To use the interface place it in the folder
# ~/.reticulum/interfaces, and add an interface entry to
# your Reticulum configuration file similar to this:

# [[Meshtastic Interface]]
# type = Meshtastic_Interface
# enabled = true
# mode = gateway
# port = / dev / ttyUSB0
# speed = 115200

from time import sleep
import sys
import threading
import time

from packet_handling import PacketHandler


# Let's define our custom interface class. It must
# be a sub-class of the RNS "Interface" class.
class MeshtasticInterface(Interface):
    # All interface classes must define a default
    # IFAC size, used in IFAC setup when the user
    # has not specified a custom IFAC size. This
    # option is specified in bytes.
    DEFAULT_IFAC_SIZE = 8
    speed_to_bitrate = {7: 500*2}

    # The following properties are local to this
    # particular interface implementation.
    owner = None
    port = None
    speed = None
    databits = None
    parity = None
    stopbits = None
    serial = None

    # All Reticulum interfaces must have an __init__
    # method that takes 2 positional arguments:
    # The owner RNS Transport instance, and a dict
    # of configuration values.
    # noinspection PyUnboundLocalVariable
    def __init__(self, owner, configuration):

        # The following lines demonstrate handling
        # potential dependencies required for the
        # interface to function correctly.
        import importlib.util
        if importlib.util.find_spec('meshtastic') is not None:
            import meshtastic
            from meshtastic.ble_interface import BLEInterface
            from meshtastic.serial_interface import SerialInterface
            from pubsub import pub
        else:
            RNS.log("Using this interface requires a meshtastic module to be installed.", RNS.LOG_CRITICAL)
            RNS.log("You can install one with the command: python3 -m pip install meshtastic", RNS.LOG_CRITICAL)
            RNS.panic()

        # We start out by initialising the super-class
        super().__init__()

        # To make sure the configuration data is in the
        # correct format, we parse it through the following
        # method on the generic Interface class. This step
        # is required to ensure compatibility on all the
        # platforms that Reticulum supports.
        ifconf = Interface.get_config_obj(configuration)

        # Read the interface name from the configuration
        # and set it on our interface instance.
        name = ifconf["name"]
        self.name = name

        # We read configuration parameters from the supplied
        # configuration data, and provide default values in
        # case any are missing.
        port = ifconf["port"] if "port" in ifconf else None
        ble_port = ifconf["ble_port"] if "ble_port" in ifconf else None
        speed = int(ifconf["data_speed"]) if "data_speed" in ifconf else 6

        # All interfaces must supply a hardware MTU value
        # to the RNS Transport instance. This value should
        # be the maximum data packet payload size that the
        # underlying medium is capable of handling in all
        # cases without any segmentation.
        self.HW_MTU = 564

        # We initially set the "online" property to false,
        # since the interface has not actually been fully
        # initialised and connected yet.
        self.online = False

        # In this case, we can also set the indicated bit-
        # rate of the interface to the serial port speed.
        self.bitrate = self.speed_to_bitrate[speed]

        # Configure internal properties on the interface
        # according to the supplied configuration.
        self.owner = owner
        self.port = port
        self.ble_port = ble_port
        self.speed = speed
        self.timeout = 100
        self.interface = None
        self.packet_queue = []
        self.packet_index = 0
        self.hop_limit = 1

        pub.subscribe(self.process_message, "meshtastic.receive")
        pub.subscribe(self.connection_complete, "meshtastic.connection.established")
        pub.subscribe(self.connection_closed, "meshtastic.connection.lost")

        # Since all required parameters are now configured,
        # we will try opening the serial port.
        try:
            self.open_interface()
        except Exception as e:
            RNS.log("Could not open meshtastic interface " + str(self), RNS.LOG_ERROR)
            raise e

        # If opening the port succeeded, run any post-open
        # configuration required.

    # Open the meshtastic interface with supplied configuration
    # parameters and store a reference to the open port.
    def open_interface(self):
        if self.port:
            RNS.log("Opening serial port " + self.port + "...", RNS.LOG_VERBOSE)
            from meshtastic.serial_interface import SerialInterface
            self.interface = SerialInterface(devPath=self.port)
        elif self.ble_port:
            RNS.log("Opening ble device " + self.ble_port + "...", RNS.LOG_VERBOSE)
            from meshtastic.ble_interface import BLEInterface
            self.interface = BLEInterface(address=self.ble_port)
        else:
            raise ValueError(f"No port or ble_port specified for {self}")

    # The only thing required after opening the port
    # is to wait a small amount of time for the
    # hardware to initialise and then start a thread
    # that reads any incoming data from the device.
    def configure_device(self):
        thread = threading.Thread(target=self.write_loop)
        thread.daemon = True
        thread.start()
        self.online = True
        RNS.log("Serial port " + self.port + " is now open", RNS.LOG_VERBOSE)

    # This method will be called from our read-loop
    # whenever a full packet has been received over
    # the underlying medium.
    def process_incoming(self, data):
        # Update our received bytes counter
        self.rxb += len(data)

        # And send the data packet to the Transport
        # instance for processing.
        self.owner.inbound(data, self)

    # The running Reticulum Transport instance will
    # call this method on the interface whenever the
    # interface must transmit a packet.
    def process_outgoing(self, data:bytes):
        RNS.log("Outgoing")
        if self.online:
            # Then write the framed data to the port
            self.packet_queue.append(PacketHandler(data, self.packet_index))
            self.packet_index += 1
            self.packet_index = self.packet_index % 256

            # Update the transmitted bytes counter
            # and ensure that all data was written
            self.txb += len(data)

    def process_message(self, packet, interface):
        """Process meshtastic traffic incoming to system"""
        # RNS.log(packet)
        pass

    def write_loop(self):
        import meshtastic
        while True:
            data = None
            while not data and self.packet_queue:
                current_packet = self.packet_queue[0]
                data = current_packet.get_next()
                if not data:
                    self.packet_queue.pop(0)
            if data:
                RNS.log(f'Sending: {data}')
                self.interface.sendData(data,
                                   portNum=meshtastic.portnums_pb2.PRIVATE_APP,
                                   wantAck=False,
                                   wantResponse=False,
                                   channelIndex=0,
                                   hopLimit=self.hop_limit)
            time.sleep(.4)  # Make sending rate dynamic

    def connection_complete(self, interface):
        """Process meshtastic connection opened"""
        RNS.log("Connected")
        self.online = True
        self.interface = interface

    def connection_closed(self, interface):
        """Process meshtastic traffic incoming to system"""
        RNS.log("Disconnected")
        self.online = False

    # Signal to Reticulum that this interface should
    # not perform any ingress limiting.
    @staticmethod
    def should_ingress_limit():
        return False

    # We must provide a string representation of this
    # interface, that is used whenever the interface
    # is printed in logs or external programs.
    def __str__(self):
        return "MeshtasticInterface[" + self.name + "]"


# Finally, register the defined interface class as the
# target class for Reticulum to use as an interface
interface_class = MeshtasticInterface
