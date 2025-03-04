# RNS_Over_Meshtastic
Interface for RNS using Meshtastic as the underlying networking layer to utilize existing high speed meshtastic hardware.

## Usage
- Install Meshtastic Python Library
- Add the file [Meshtastic_Interface.py](Interface%2FMeshtastic_Interface.py) to your interfaces folder for reticulum
- Modify the node config file and add the following
```
 [[Meshtastic Interface]]
  type = Meshtastic_Interface
  enabled = true
  mode = gateway
  port = /dev/[path to device]  # Optional: Meshtastic serial device port
  ble_port = short_1234  # Optional: Meshtastic BLE device ID (Replacement for serial port)
  data_speed = 8  # Radio speed setting desired for the network(do not use long-fast)
```

- Radio settings and their associated transfer speeds are shown below (from [Meshtastic_Interface.py](Interface%2FMeshtastic_Interface.py))
```python
speed_to_delay = {8: .4,  # Short-range Turbo (recommended)
                  6: 1,  # Short Fast (best if short turbo is unavailable)
                  5: 3,  # Short-range Slow (best if short turbo is unavailable)
                  7: 12,  # Long Range - moderate Fast
                  4: 4,  # Medium Range - Fast  (Slowest recommended speed)
                  3:6,  # Medium Range - Slow
                  1: 15,  # Long Range - Slow
                  0: 8  # Long Range - Fast
                  }
```
- Use the number on the left to set the speed and change the number on the right to change the max transmission rate from the radio
