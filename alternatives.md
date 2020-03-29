# alternatives to the M74HC4066B1R

## Relay

No special configuration is needed.
1. Connect the motherboard pins across the NO terminals of the relay.
2. Connect the control pin of the relay to the selected GPIO pin on the Pi.
Additional circuitry may be required to safely drive the relay though this will depend on the relay in use.

## NPN Transistor

1. Determine which of the two pins on the motherboard is ground and which is the input. These are unlikely to be marked as the case buttons do not care.
See below for one method of doing this.
2. Connect the ground pin to the transistor's emitter.
3. Connect the other pin to the transistor's collector.
4. Connect your chosen GPIO to the transistor's base.

## Direct Conection to Pi's GPIO

This is not recommnded and has not been tested.

### Cautions

- The pull up for the input pin on the motherboard may be to a source higher than 3.3v. If so this will likely damage your Pi, especially if your selected GPIO is set to an input.
- To avoid side effects on the main PC, you must use a GPIO that remains high during (re)boot and when the Pi is off.
- Behaviour when the Pi is disconnected from power and ground while still connected to the motherboard header(s) is unknown.

### Procedure

1. Determine which of the two pins on the motherboard is ground and which is the input.
2. Connect the input pin to your selected GPIO.
3. Configure the fakewake daemon to be active low on that GPIO.

## Finding The Motherboard's Input Pin

If you're lucky this will be marked on the board or shown in the manual.

This is one possible way to do this. Use at your own risk.

### Requirements

- 2 x Male to Female jumper wires
- Tools to open your PC's case.

### Procedure

1. Disconnect all drives from the motherboard and from the PSU. This is to protect the dives from corruption and/or damage.
2. Optionaly, remove any unnecessary PCI/PCIe cards and USB devices.
3. Disconnect the power/reset button from the front panel header.
4. Connect one jump wire to a known ground pin. For example the - pin for one of the case LEDs.
5. Connect the other jump wire to one of the pins for the button being investigated.
6. Briefly connect the two jump wires together.

If you have the correct pin the board will power up. If it doesn't try the other one of the pair.

When trying to identify the pins for the reset button, it is likely the board will need to be on. The reset button is not active when the board is in the off state.
