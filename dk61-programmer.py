import argparse
import json
from gk64 import GK64, CommandPacket
import logging
import sys
from enum import Enum

logger = None


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
class KeyboardLayerDataType:
    Invalid = 0
    KeySet = 1
    LEData = 3
    Macros = 4
    KeyPressLightingEffect = 5
    Lighting = 6
    FnKeySet = 7


class DK61(GK64):
    mapKeycodes = {
        "None": "0",

        "Esc": "0x02002900",
        "Disabled": "0x02000000",
        "F1": "0x02003A00",
        "F2": "0x02003B00",
        "F3": "0x02003C00",
        "F4": "0x02003D00",
        "F5": "0x02003E00",
        "F6": "0x02003F00",
        "F7": "0x02004000",
        "F8": "0x02004100",
        "F9": "0x02004200",
        "F10": "0x02004300",
        "F11": "0x02004400",
        "F12": "0x02004500",

        "PrintScreen": "0x02004600",
        "ScrollLock": "0x02004700",
        "Pause": "0x02004800",

        "BackTick": "0x02003500",
        "1": "0x02001E00",
        "2": "0x02001F00",
        "3": "0x02002000",
        "4": "0x02002100",
        "5": "0x02002200",
        "6": "0x02002300",
        "7": "0x02002400",
        "8": "0x02002500",
        "9": "0x02002600",
        "0": "0x02002700",
        "Subtract": "0x02002D00",
        "Add": "0x02002E00",
        "Backspace": "0x02002A00",

        "Insert": "0x02004900",
        "Home": "0x02004A00",
        "PageUp": "0x02004B00",

        "Tab": "0x02002B00",
        "Q": "0x02001400",
        "W": "0x02001A00",
        "E": "0x02000800",
        "R": "0x02001500",
        "T": "0x02001700",
        "Y": "0x02001C00",
        "U": "0x02001800",
        "I": "0x02000C00",
        "O": "0x02001200",
        "P": "0x02001300",
        "OpenSquareBrace": "0x02002F00",
        "CloseSquareBrace": "0x02003000",
        "Backslash": "0x02003100",
        "Backslash1": "0x02003200",

        "Delete": "0x02004C00",
        "End": "0x02004D00",
        "PageDown": "0x02004E00",

        "CapsLock": "0x02003900",
        "A": "0x02000400",
        "S": "0x02001600",
        "D": "0x02000700",
        "F": "0x02000900",
        "G": "0x02000A00",
        "H": "0x02000B00",
        "J": "0x02000D00",
        "K": "0x02000E00",
        "L": "0x02000F00",
        "Semicolon": "0x02003300",
        "Quotes": "0x02003400",
        "Enter": "0x02002800",
        "LShift": "0x02000002",
        "AltBackslash": "0x02006400",
        "Z": "0x02001D00",
        "X": "0x02001B00",
        "C": "0x02000600",
        "V": "0x02001900",
        "B": "0x02000500",
        "N": "0x02001100",
        "M": "0x02001000",
        "Comma": "0x02003600",
        "Period": "0x02003700",
        "Slash": "0x02003800",
        "RShift": "0x02000020",
        "Up": "0x02005200",
        "LCtrl": "0x02000001",
        "LWin": "0x02000008",
        "LAlt": "0x02000004",
        "Space": "0x02002C00",
        "RAlt": "0x02000040",
        "RWin": "0x02000080",
        "Menu": "0x02006500",
        "RCtrl": "0x02000010",
        "Left": "0x02005000",
        "Down": "0x02005100",
        "Right": "0x02004F00",

        "NumLock": "0x02005300",
        "NumPadSlash": "0x02005400",
        "NumPadAsterisk": "0x02005500",
        "NumPadSubtract": "0x02005600",
        "NumPad7": "0x02005F00",
        "NumPad8": "0x02006000",
        "NumPad9": "0x02006100",
        "NumPadAdd": "0x02005700",
        "NumPad4": "0x02005C00",
        "NumPad5": "0x02005D00",
        "NumPad6": "0x02005E00",
        "NumPad1": "0x02005900",
        "NumPad2": "0x02005A00",
        "NumPad3": "0x02005B00",
        "NumPad0": "0x02006200",
        "NumPadPeriod": "0x02006300",
        "NumPadEnter": "0x02005800",

        "OpenMediaPlayer": "0x03000183",
        "MediaPlayPause": "0x030000CD",
        "MediaStop": "0x030000B7",
        "MediaPrevious": "0x030000B6",
        "MediaNext": "0x030000B5",
        "VolumeUp": "0x030000E9",
        "VolumeDown": "0x030000EA",
        "VolumeMute": "0x030000E2",

        "BrowserSearch": "0x03000221",
        "BrowserStop": "0x03000226",
        "BrowserBack": "0x03000224",
        "BrowserForward": "0x03000225",
        "BrowserRefresh": "0x03000227",
        "BrowserFavorites": "0x0300022A",
        "BrowserHome": "0x03000223",
        "OpenEmail": "0x0300018A",
        "OpenMyComputer": "0x03000194",
        "OpenCalculator": "0x03000192",
        "Copy": "0x02000601",
        "Paste": "0x02001901",
        "Screenshot": "0x02004600",

        "MouseLClick": "0x01010001",
        "MouseRClick": "0x01010002",
        "MouseMClick": "0x01010004",
        "MouseBack": "0x01010008",
        "MouseAdvance": "0x01010010",

        "TempSwitchLayerBase": "0x0a070001",
        "TempSwitchLayer1": "0x0a070002",
        "TempSwitchLayer2": "0x0a070003",
        "TempSwitchLayer3": "0x0a070004",
        "TempSwitchLayerDriver": "0x0a070005",

        "Power": "0x02006600",
        "Clear": "0x02006700",
        "F13": "0x02006800",
        "F14": "0x02006900",
        "F15": "0x02006A00",
        "F16": "0x02006B00",
        "F17": "0x02006C00",
        "F18": "0x02006D00",
        "F19": "0x02006E00",
        "F20": "0x02006F00",
        "F21": "0x02007000",
        "F22": "0x02007100",
        "F23": "0x02007200",
        "F24": "0x02007300",
        "NumPadComma": "0x02008500",
        "IntlRo": "0x02008700",
        "KanaMode": "0x02008800",
        "IntlYen": "0x02008900",
        "Convert": "0x02008A00",
        "NonConvert": "0x02008B00",

        "Lang3": "0x02009200",
        "Lang4": "0x02009300",

        "ToggleLockWindowsKey": "0x0A020002",
        "ToggleBluetooth": "0x0A020007",
        "ToggleBluetoothNoLED": "0x0A020008",

        "DriverLayerButton": "0x0A060001",
        "Layer1Button": "0x0A060002",
        "Layer2Button": "0x0A060003",
        "Layer3Button": "0x0A060004",

        "NextLightingEffect": "0x09010010",
        "NextReactiveLightingEffect": "0x09010011",
        "BrightnessUp": "0x09020001",
        "BrightnessDown": "0x09020002",
        "LightingSpeedDecrease": "0x09030002",
        "LightingSpeedIncrease": "0x09030001",
        "LightingPauseResume": "0x09060001",
        "ToggleLighting": "0x09060002"
    }
    layerCodes = {
        "Layer1": "0x23",
        "layer2": "0x24",
        "Layer3": "0x25",
        "FnLayer1": "0x23",
        "Fnlayer2": "0x24",
        "FnLayer3": "0x25"
    }

    def __init__(self):
        GK64.__init__(self)

    def setLayer(self):
        pass

    def setColor(self):
        pass

    def wipeoutLayer(self, layercode):
        pass

    def setAllLayers(self, keymap):
        global logger
        for layerName, layerKeymap in keymap["layers"].items():
            # first check that all keys inside the layer are valid
            layercode = 0
            self.wipeoutLayer(layercode)
            for srcKey, dstKey in layerKeymap.items():
                if not srcKey in self.mapKeycodes:
                    raise LookupError("Source Keyname is wrong: %s inside %s" % (srcKey, layerName))
                if not dstKey in self.mapKeycodes:
                    raise LookupError("Destination Keyname is wrong: %s inside %s" % (dstKey, layerName))

    def commandInfo(self):
        pass

    def commandLayerSetKeyValues(self):
        pass

    def commandLayerFnSetKeyValues(self):
        pass

    def commandLayerSetLightValues(self):
        pass

    def commandLayerResetDataType(self):
        pass

    def test(self):
        self.send_cmd(OpCodes.SetLayer.value, KeyboardLayer.Layer3.value, verbose=True)


def parseCommandLineArguments():
    parser = argparse.ArgumentParser(description="Programmer for the Kemove DK61 Keyboard")
    parser.add_argument("--keymap", help="keymap.json file")
    args = parser.parse_args()
    return args


def checkKeymapFile(keymapFilename):
    global logger
    keymap = json.load(open(keymapFilename, "r"))
    for key, value in keymap["layers"].items():
        logger.debug("Analyze layer: %s" % key)
    return keymap


def main(args):
    global logger
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logger = logging.getLogger("dk61")
    logger.info("Hello world")
    logger.debug("Reading from file: %s" % args.keymap)
    keymap = checkKeymapFile(args.keymap)
    dk61 = DK61()
    dk61.test()
    # dk61.setAllLayers(keymap)


if __name__ == "__main__":
    args = parseCommandLineArguments()
    main(args)
