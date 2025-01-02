import struct

class PacketHandler:
    struct_format = 'Bb'
    def __init__(self, data=None, index=None, max_payload=200):
        self.max_payload = max_payload
        self.index = index
        self.data_dict = {}
        self.loop_pos = 0
        self.done = False
        if data:  # Means we are sending
            self.split_data(data)

    def split_data(self, data: bytes):
        """Split data into even chunks and add metadata to it"""
        data_list = []
        data_len = len(data)
        num_packets = data_len//self.max_payload + 1  # Number of packets needed to hold the data
        packet_size = data_len//num_packets + 1
        for i in range(0, data_len, packet_size):
            data_list.append(data[i:i + packet_size])
        for i, packet in enumerate(data_list):
            pos = i
            if i == len(data_list)-1:
                pos = -i
            meta_data = struct.pack(self.struct_format, self.index, pos)
            self.data_dict[i] = meta_data+packet

    def get_next(self):
        """get next packet to send"""
        ret = self.get_index(self.loop_pos)
        self.loop_pos += 1
        if max(self.data_dict.keys()) < self.loop_pos:
            self.loop_pos = 0
            self.done = True
        return ret

    def get_index(self, i):
        """Get the packet at an index"""
        if i in self.data_dict:
            return self.data_dict[i]

    def is_done(self):
        return self.done

    def process_packet(self, packet: bytes):
        """Returns data if the packet is complete, and nothing if it isn't"""
        meta_data = packet[:len(self.struct_format)]
        new_index, pos = struct.unpack(self.struct_format, meta_data)
        self.index = new_index
        self.data_dict[abs(pos)] = packet
        if pos < 0:
            return self.assemble_data()
        return None

    def check_data(self):
        """check content of data dict against the expected content"""
        expected = 0
        for key in sorted(self.data_dict.keys()):
            if key != expected:
                return False
            expected += 1
        return True

    def assemble_data(self):
        """Put all the data together and return it or nothing if it fails"""
        if self.check_data():
            data = b''
            for key in sorted(self.data_dict.keys()):
                data += self.data_dict[key][len(self.struct_format):]
            return data
        else:
            return None


if __name__ == '__main__':
    handler = PacketHandler(b'hello_world'*56, 0)
    receive = PacketHandler()
    while not handler.is_done():
        packet = handler.get_next()
        result = receive.process_packet(packet)
    print(result == b'hello_world'*56)
