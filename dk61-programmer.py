#!/usr/bin/python3
# dk61-programmer.py - programming the keyboard from Mac OS
#
#
# Copyright (c) 2020 Edmund Bayerle <e.bayerle@gmail.com>
# Portions of this code are Copyright (c) 2019 Will Woods <w@wizard.zone>
#
# You shouldn't be using this, because it's horrible, but if you are,
# consider it licensed as GPLv2+. Also, I'm sorry.

import json
import logging
import sys
from enum import Enum
import struct
from collections import namedtuple
import hid
from pprint import PrettyPrinter

import argparse

logger = None
pp = PrettyPrinter()


# unoptimized, translated from http://mdfs.net/Info/Comp/Comms/CRC16.htm
def crc16(data, poly=0x1021, iv=0x0000, xorf=0x0000):
    crc = int(iv)
    for b in bytearray(data):
        crc ^= (b << 8)
        for _ in range(0, 8):
            crc <<= 1
            if crc & 0x10000:
                crc = (crc ^ poly) & 0xffff  # xor with poly and trunc to 16bit
    return (crc & 0xffff) ^ xorf


def crc16_usb(data, iv=0xffff):
    return crc16(data, poly=0x8005, iv=iv, xorf=0xffff)


def mycrc16(data, iv=0xffff):
    return crc16(data, poly=0x1021, iv=iv, xorf=0x0000)


def hexdump_line(data):
    linedata = bytearray(data[:16])
    hexbytes = ["%02x" % b for b in linedata] + (["  "] * (16 - len(linedata)))
    printable = ''.join(chr(b) if b >= 0x20 and b < 0x7f else '.' for b in linedata)
    return '{}  {}   {} {}'.format(' '.join(hexbytes[:8]), ' '.join(hexbytes[8:]), printable[:8],
                                   printable[8:])


def hexdump_iterlines(data, start=0):
    offset = 0
    while offset < len(data):
        yield "{:08x}  {}".format(start + offset, hexdump_line(data[offset:offset + 0x10]))


def hexdump(data, start=0):
    for line in hexdump_iterlines(data, start):
        print(line)


# USB Packet Structure:
#
# Data is usually sent to endpoint 4, and the device answers on endpoint 3.
# In firmware update mode (see below), send to endpoint 2 and get answers on 1.
#
# Outgoing and incoming packets are always 0x64 bytes long, and have roughly
# the same structure. Example outgoing packet data:
#
#   01 01 00 00 00 00 74 1b  00 00 00 00 00 00 00 00   ......t. ........
#   00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   ........ ........
#   00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   ........ ........
#   00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   ........ ........
#
# And the reply:
#
#   01 01 01 00 00 00 35 25  01 39 10 02 09 01 00 00   ......5% .9......
#   00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   ........ ........
#   00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   ........ ........
#   00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00   ........ ........
#
# The structure is as follows:
# * 8 byte header, then up to 56 (0x38) bytes of data (padded with zeros)
# * Command header: 01 01 00 00 00 00 74 1b
#   * Byte 0: Command
#   * Byte 1: Subcommand
#   * Byte 2-3: Offset (used for uploading firmware in chunks)
#   * Byte 4: padding? (always 00..)
#   * Byte 5: Size of payload (max 0x38)
#   * Byte 6-7: checksum
#     * CRC16/CCITT-FALSE: little-endian, polynomial 0x1021, IV 0xFFFF
#     * Calculated over the whole 64-byte packet, with checksum = 00 00
#   * Byte 8-63: Payload data, padded with 00s to 64 bytes total

# * Reply header: 01 01 01 00 00 00 35 25
#   * Byte 0: Command
#   * Byte 1: Subcommand
#   * Byte 2: Result - 01 for success, 00 otherwise
#   * Byte 3-5: unused/padding (always 00..)
#   * Byte 6-7: checksum, as above
#   * Byte 8-63: payload (padded to 64 bytes long with 0x00's)
#
# (You'll note that the Reply doesn't seem to tell you how much data it's
# sending you, which makes interpreting the reply a little trickier..)


class BindataMixin(object):
    _struct = None

    @classmethod
    def _unpack(cls, buf):
        return cls(*cls._struct.unpack(buf))

    def _pack(self):
        return self._struct.pack(*self)

    def _hexdump(self):
        data = self._pack()
        size = self._struct.size
        return '\n'.join(hexdump_line(data[s:s + 0x10]) for s in range(0, size, 0x10))

    def _calculate_checksum(self):
        return mycrc16(self._replace(checksum=0)._pack())

    def _replace_checksum(self):
        return self._replace(checksum=self._calculate_checksum())

    def _checksum_ok(self):
        return self.checksum == self._calculate_checksum()


PacketStruct = struct.Struct("<BBHBBH56s")

CommandPacketTuple = namedtuple("CommandPacketTuple", "cmd subcmd offset pad1 length checksum data")


class CommandPacket(CommandPacketTuple, BindataMixin):
    _struct = PacketStruct


ReplyPacketTuple = namedtuple("ReplyPacketTuple", "cmd subcmd result pad1 pad2 checksum data")


class ReplyPacket(ReplyPacketTuple, BindataMixin):
    _struct = PacketStruct


BImgHdrTuple = namedtuple("BImgHdrTuple", "magic checksum ts size datachecksum itype name")


class BImgHdr(BImgHdrTuple, BindataMixin):
    _struct = struct.Struct("<IIIIII8s")


class Error(Exception):
    """Base class for exceptions in this module"""
    pass


class CmdError(Error):
    """Exception raised when the GK6x reply doesn't indicate success.
 
    Attributes:
        message: explanation of the error
        reply: the ReplyPacket object
    """

    def __init__(self, message, reply):
        self.message = message
        self.reply = reply


class OpCodes(Enum):
    Info = 0x01
    RestartKeyboard = 0x03
    SetLayer = 0x0B
    Ping = 0x0C
    DriverMacro = 0x15
    DriverLayerSetKeyValues = 0x16
    DriverLayerSetConfig = 0x17
    LayerResetDataType = 0x21
    LayerSetKeyValues = 0x22
    LayerSetMacros = 0x25
    LayerSetKeyPressLightingEffect = 0x26
    LayerSetLightValues = 0x27
    LayerFnSetKeyValues = 0x31


class KeyboardLayer(Enum):
    Invalid = 0
    Base = 1
    Layer1 = 2
    Layer2 = 3
    Layer3 = 4
    Driver = 5


# used by LayerResetDataType
class KeyboardLayerDataType(Enum):
    Invalid = 0
    KeySet = 1
    LEData = 3
    Macros = 4
    KeyPressLightingEffect = 5
    Lighting = 6
    FnKeySet = 7


class DK61(object):
    VendorId = 0x1ea7
    ProductId = 0x0907

    layerCodes = {
        "Layer1": {
            "code": KeyboardLayer.Layer1.value,
            "isFnLayer": False
        },
        "Layer2": {
            "code": KeyboardLayer.Layer2.value,
            "isFnLayer": False
        },
        "Layer3": {
            "code": KeyboardLayer.Layer3.value,
            "isFnLayer": False
        },
        "FnLayer1": {
            "code": KeyboardLayer.Layer1.value,
            "isFnLayer": True
        },
        "FnLayer2": {
            "code": KeyboardLayer.Layer2.value,
            "isFnLayer": True
        },
        "FnLayer3": {
            "code": KeyboardLayer.Layer3.value,
            "isFnLayer": True
        }
    }

    def __init__(self):
        logger.debug("DK61: init called")
        self.hidDevice = self.findDevice(self.VendorId, self.ProductId, 1)
        self.keyboardMappings = None
        self.mapKeycodes = None
        self.keyboardKeys = None
        self.loadKeyboardMappings()

    def __enter__(self):
        if self.hidDevice is not None:
            logger.debug("Hey, we have a HID device")
            self.hidDevice.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.debug("DK61: exit called")
        if self.hidDevice is not None:
            self.hidDevice.__exit__(exc_type, exc_val, exc_tb)

    def loadKeyboardMappings(self):
        with open("keyboard-mappings.json", "r") as f:
            self.keyboardMappings = json.load(f)
            self.mapKeycodes = self.keyboardMappings["mapKeycodes"]
            self.keyboardKeys = self.keyboardMappings["keyboardKeys"]
        return self.keyboardMappings

    def findDevice(self, vendorId, productId, interfaceNumber):
        allHIDDevices = hid.enumerate()
        for oneDevice in allHIDDevices:
            if oneDevice["vendor_id"] == vendorId and oneDevice["product_id"] == productId and \
                    oneDevice["interface_number"] == interfaceNumber:
                path = oneDevice["path"]
                logger.debug(
                    "-------------------------------------------------------------------------------------------"
                )
                logger.debug("Found device with path: %s" % path)
                logger.debug(pp.pformat(oneDevice))
                return hid.Device(path=path)
        return None

    def sendCommand(self,
                    cmd,
                    subcmd,
                    offset=0,
                    length=0,
                    data=None,
                    getreply=True,
                    verbose=False,
                    replytimeout=100,
                    smallOffset=False):
        if offset & 0xff000000:
            raise ValueError("offset {:#010x} > 0x00ffffff".format(offset))
        if not data:
            data = bytearray(0x38)
        if smallOffset:
            pkt = CommandPacket(cmd, subcmd, offset & 0xffff, length, 0, 0, data)._replace_checksum()
        else:
            pkt = CommandPacket(cmd, subcmd, offset & 0xffff, offset >> 16, length, 0,
                                data)._replace_checksum()
        if verbose:
            print("send packet:")
            print(pkt._hexdump())
        self.hidDevice.write(pkt._pack())
        if not getreply:
            return
        r = ReplyPacket._unpack(self.hidDevice.read(0x40, timeout=replytimeout))
        if verbose:
            print("recv reply:")
            print(r._hexdump())
        return r

    def setAllLayers(self, keymap):
        for layerName, layerKeymap in keymap["keyLayers"].items():
            # first check that all keys inside the layer are valid
            logger.debug(
                "-----------------------------------------------------------------------------------------")
            logger.debug("Set layer %s" % layerName)
            layercode = 0
            for srcKeyName, dstKeyName in layerKeymap.items():
                if not srcKeyName in self.mapKeycodes:
                    raise LookupError("Source Keyname is wrong: %s inside %s" % (srcKeyName, layerName))
                if not dstKeyName in self.mapKeycodes:
                    raise LookupError("Destination Keyname is wrong: %s inside %s" % (dstKeyName, layerName))
            driverKeycodes = []
            unusedKeyCode = int(self.mapKeycodes["UnusedKey"], 0)
            for key in self.keyboardKeys:
                keyName = key["KeyName"]
                if keyName in layerKeymap:
                    dstKeyName = layerKeymap[keyName]
                    keyCode = int(self.mapKeycodes[dstKeyName], 0)
                else:
                    keyCode = unusedKeyCode
                # logger.debug("Use %d as keycode for %s" % (keyCode, keyName))
                driverKeycodes.append(keyCode)
            layerCodeInfo = self.layerCodes[layerName]
            layerCode = layerCodeInfo["code"]
            logger.debug("Set keycodes for %s" % layerName)
            if layerCodeInfo["isFnLayer"]:
                self.wipeoutLayer(layerCode, KeyboardLayerDataType.FnKeySet.value)
                self.commandLayerFnSetKeyValues(layerCode, driverKeycodes)
            else:
                self.wipeoutLayer(layerCode, KeyboardLayerDataType.KeySet.value)
                self.commandLayerSetKeyValues(layerCode, driverKeycodes)

    @staticmethod
    def getColorDefinition(colorDefinitions, colorName):
        if colorName is not None and colorName in colorDefinitions:
            return int(colorDefinitions[colorName], 0)
        if "default" in colorDefinitions:
            return int(colorDefinitions["default"], 0)
        return 0x000000

    def setStaticColorLayers(self, keymap):
        colorDefinitions = keymap["colorDefinitions"]
        for layerName, layerColorMap in keymap["staticColorLayers"].items():
            defaultColorName = layerColorMap["default"] if "default" in layerColorMap else None
            defaultColor = self.getColorDefinition(colorDefinitions, defaultColorName)
            driverColorCodes = []
            numKeys = 132
            for i in range(0, numKeys):
                driverColorCodes.append(defaultColor)
            for key in self.keyboardKeys:
                keyName = key["KeyName"]
                if keyName in layerColorMap:
                    colorCode = self.getColorDefinition(colorDefinitions, layerColorMap[keyName])
                    locationCode = key["LocationLED"]
                    driverColorCodes[locationCode] = colorCode
            layerCodeInfo = self.layerCodes[layerName]
            layerCode = layerCodeInfo["code"]
            logger.debug("Set static light for layer %s with code %d and %d keys" %
                         (layerName, layerCode, len(driverColorCodes)))
            try:
                self.wipeoutLayer(layerCode, KeyboardLayerDataType.Lighting.value)
            except:
                logger.debug("Ignoring error: no reply")
            self.commandLayerSetStaticLighting(layerCode, driverColorCodes)

    def write32Bits(self, data, position, value):
        data[position + 0] = value & 0xff
        data[position + 1] = (value >> 8) & 0xff
        data[position + 2] = (value >> 16) & 0xff
        data[position + 3] = (value >> 24) & 0xff

    def write16Bits(self, data, position, value):
        data[position + 0] = value & 0xff
        data[position + 1] = (value >> 8) & 0xff

    def commandLayerSetStaticLighting(self, layerCode, driverColorCodes):
        maxNumberOfEffects = 32
        effectHeaderSize = 16
        totalEffectsHeaderSize = maxNumberOfEffects * effectHeaderSize
        logger.debug("Total Effects Header Size is: %d" % totalEffectsHeaderSize)
        numKeys = 132  # or better len(driverColorCodes)
        driverColorCodesSize = numKeys * 4
        paramHeaderSize = 4
        dataBufferSize = totalEffectsHeaderSize + (paramHeaderSize + driverColorCodesSize)

        # fill the buffer with data
        data = bytearray(dataBufferSize)

        # fill the header for static lighting, pointing to the start of static lighting array
        self.write32Bits(data, 0, totalEffectsHeaderSize)  # start of effect data
        self.write32Bits(data, 4, 1)  # effect params
        self.write32Bits(data, 8, 0)
        self.write32Bits(data, 12, 0)
        print('Hello world')

        for i in range(1, maxNumberOfEffects):
            self.write32Bits(data, i * effectHeaderSize + 0, -1)  # unused effects
            self.write32Bits(data, i * effectHeaderSize + 4, -1)
            self.write32Bits(data, i * effectHeaderSize + 8, -1)
            self.write32Bits(data, i * effectHeaderSize + 12, -1)

        # local header
        logger.debug("DriverColorCodes has size: %d" % driverColorCodesSize)
        typeStatic = 0
        self.write16Bits(data, totalEffectsHeaderSize, typeStatic)
        self.write16Bits(data, totalEffectsHeaderSize + 2, driverColorCodesSize)

        colorCodePosition = totalEffectsHeaderSize + paramHeaderSize
        for colorCode in driverColorCodes:
            self.write32Bits(data, colorCodePosition, colorCode)
            colorCodePosition += 4

        # now chunk the data buffer in smaller packets
        maxChunkSize = 0x38
        offset = 0
        packetNumber = 0
        while offset < dataBufferSize:
            chunkSize = min(maxChunkSize, dataBufferSize - offset)
            packetData = data[offset:offset + chunkSize]
            logger.debug("Send packet %d at offset: %d" % (packetNumber, offset))
            result = self.sendCommand(OpCodes.LayerSetLightValues.value, layerCode, offset, chunkSize,
                                      packetData, True, True, 1000)
            if result.cmd != OpCodes.LayerSetLightValues.value:
                raise Error("Error returned")
            offset += chunkSize
            packetNumber += 1

    def commandCommonLayerSetKeyValues(self, opcode, layerCode, driverKeycodes):
        offset = 0
        driverKeycodesSize = len(driverKeycodes)
        driverKeycodesCounter = 0
        while driverKeycodesCounter < driverKeycodesSize:
            keyBufferSize = 14 * 4
            data = bytearray(keyBufferSize)
            keyBufferCounter = 0
            while keyBufferCounter < keyBufferSize and driverKeycodesCounter < driverKeycodesSize:
                keycode = driverKeycodes[driverKeycodesCounter]
                driverKeycodesCounter += 1
                self.write32Bits(data, keyBufferCounter, keycode)
                keyBufferCounter += 4
            result = self.sendCommand(opcode, layerCode, offset, keyBufferCounter, data, True, True, 100,
                                      True)
            if result.cmd != opcode:
                raise Error("Error returned")
            offset += keyBufferCounter

    def commandLayerSetKeyValues(self, layerCode, driverKeycodes):
        self.commandCommonLayerSetKeyValues(OpCodes.LayerSetKeyValues.value, layerCode, driverKeycodes)

    def commandLayerFnSetKeyValues(self, layerCode, driverKeycodes):
        self.commandCommonLayerSetKeyValues(OpCodes.LayerFnSetKeyValues.value, layerCode, driverKeycodes)

    def wipeoutLayer(self, layerCode, dataType, getreply=True):
        self.sendCommand(OpCodes.LayerResetDataType.value, layerCode, dataType, 0, None, getreply, True, 1000)

    def commandLayerSetLightValues(self):
        pass

    def commandLayerResetDataType(self):
        pass

    def commandInfoGetBufferSize(self):
        result = self.sendCommand(OpCodes.Info.value, 0x09, verbose=True)
        size = (result.data[0], result.data[1])
        logger.debug("Received size tuple: %s" % pp.pformat(size))
        return size

    def commandSetActiveLayer(self, layerCode):
        self.sendCommand(OpCodes.SetLayer.value, layerCode, verbose=True)

    def test(self):
        self.commandInfoGetBufferSize()
        self.commandSetActiveLayer(KeyboardLayer.Layer3.value)


def parseCommandLineArguments():
    parser = argparse.ArgumentParser(description="Programmer for the Kemove DK61 Keyboard")
    parser.add_argument("--keymap", help="keymap.json file")
    args = parser.parse_args()
    return args


def checkKeymapFile(keymapFilename):
    with open(keymapFilename, "r") as keymapFile:
        keymap = json.load(keymapFile)
    return keymap


def main(args):
    global logger
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logger = logging.getLogger("dk61")
    logger.info("Hello world")
    logger.debug("Reading from file: %s" % args.keymap)
    keymap = checkKeymapFile(args.keymap)
    with DK61() as dk61:
        dk61.setStaticColorLayers(keymap)
        dk61.setAllLayers(keymap)


if __name__ == "__main__":
    parsedArgs = parseCommandLineArguments()
    main(parsedArgs)
