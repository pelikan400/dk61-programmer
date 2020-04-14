import hid
import pprint
import ctypes

vendorId = 0x1ea7
productId = 0x0907
pp = pprint.PrettyPrinter()




def findHidDevice(vendorId, productId, interfaceNumber):
    allHIDDevices = hid.enumerate()
    for oneDevice in allHIDDevices:
        if oneDevice["vendor_id"] == vendorId and oneDevice["product_id"] == productId and oneDevice["interface_number"] == interfaceNumber:
            print("--------------------------------------------------------------------------------------------------------------------")
            print("Found device with path: %s" % oneDevice["path"])
            pp.pprint(oneDevice)
            return oneDevice
    return None


keyboardDevice = findHidDevice(vendorId, productId, 1)

with hid.Device(path=keyboardDevice["path"]) as h:
    print('Device manufacturer: {h.manufacturer}')
    print('Product: {h.product}')
    print('Serial Number: {h.serial}')
    data=h.read(64,10)
    sendBuffer = ctypes.create_string_buffer(65)
    sendBuffer[0]=b"a"
    print("Received data from the keyboard")
    pp.pprint(data)
    pp.pprint(sendBuffer)
