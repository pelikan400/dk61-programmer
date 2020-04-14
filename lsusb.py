import usb

busses = usb.busses()
for bus in busses:
   devices = bus.devices
   for dev in devices:
      print( dev.dev )
      #print( usb.util.get_string(dev, 256, dev.iManufacturer) )
      #print( usb.util.get_langids(dev) )
      print( "Device:", dev.filename )
      print( "  idVendor: %d (0x%04x)" % (dev.idVendor, dev.idVendor) )
      print( "  idProduct: %d (0x%04x)" % (dev.idProduct, dev.idProduct) )
      print()
      print()
