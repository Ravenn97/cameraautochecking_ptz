from __future__ import division

import math

import numpy as np
from cv2 import cv2
from imutils import face_utils
import imutils

import argparse
import json
import time, sys, os, signal

sys.path.append('../pysca')

from pysca import pysca

from RealtimeInterval import RealtimeInterval
import CameraReaderAsync
from WeightedFramerateCounter import WeightedFramerateCounter

''' cambot.py
	Uses CV facial recognition to control a pan/tilt/zoom camera
	and keep a speaker centered and framed appropriately.
'''
#        if subject.isCentered \
#                 and self.requestedZoomPos > 0 \
#                 and self.requestedZoomPos < stage.trackingZoom:
#             pysca.pan_tilt(1, 0, 5, 0, stage.trackingTiltAdjustment, relative=True, blocking=True)
#             pysca.set_zoom(1, stage.trackingZoom, blocking=True)
#             self.requestedZoomPos = stage.trackingZoom
# # Tunable parameters

g_debugMode = True


class Face():
    _recentThresholdSeconds = 0

    visible = False
    didDisappear = False
    recentlyVisible = False
    lastSeenTime = 0
    firstSeenTime = 0
    xcenter = -1
    ycenter = -1

    def __init__(self, cfg):
        self._recentThresholdSeconds = cfg["recentThresholdSeconds"]

    def found(self, xcenter, ycenter):
        now = time.time()
        if not self.visible:
            self.firstSeenTime = now
        self.lastSeenTime = now
        self.xcenter = xcenter
        self.ycenter = ycenter
        self.visible = True
        self.recentlyVisible = True
        self.didDisappear = False
        return

    def lost(self):
        now = time.time()
        if self.visible:
            self.didDisappear = True
            self.firstSeenTime = 0
        else:
            self.didDisappear = False
        if now - self.lastSeenTime <= self._recentThresholdSeconds:
            self.recentlyVisible = True
        else:
            self.recentlyVisible = False
        self.visible = False
        return

    def age(self):
        now = time.time()
        if self.firstSeenTime:
            return now - self.firstSeenTime
        else:
            return 0


class Subject():
    xcenter = -1
    offsetX = 0
    offsetY = 0
    offsetHistory = []
    isPresent = False
    isCentered = True
    isFarLeft = False
    isFarRight = False
    isFarUp = False
    isFarDown = False
    debug_mode = False

    def __init__(self, cfg, debug_mode=False):
        self.centeredPercentVariance = cfg["centeredPercentVariance"]
        self.offCenterPercentVariance = cfg["offCenterPercentVariance"]

    def manageOffsetHistory(self, rawOffset):
        self.offsetHistory.append(rawOffset)
        if (len(self.offsetHistory) > 10):
            self.offsetHistory.pop(0)
        return

    def isVolatile(self):
        if len(self.offsetHistory) < 2:
            return True
        # volatility is shown when consecutive offsets have large
        # deltas. We will calculate the deltas and average them.
        deltas = []
        history = iter(self.offsetHistory)
        prior = history.next()
        current = history.next()
        try:
            while True:
                deltas.append(abs(current - prior))
                prior = current
                current = history.next()
        except StopIteration:
            pass
        avgDelta = float(sum(deltas) / len(deltas))
        return True if avgDelta > 9 else False

    def evaluate(self, face, scene):
        if not face.visible:
            if not face.recentlyVisible:
                # If we haven't seen a face in a while, reset
                self.xcenter = -1
                self.ycenter = -1
                self.offsetX = 0
                self.offsetY = 0
                self.isPresent = False
                self.isCentered = True
                self.isFarLeft = False
                self.isFarRight = False
                self.isFarUp = False
                self.isFarDown = False

            # If we still have a recent subject location, keep it
            self.isPresent = True
            return

        # We have a subject and can characterize location in the frame
        self.isPresent = True
        self.xcenter = face.xcenter
        self.ycenter = face.ycenter
        frameCenterX = scene.imageWidth / 2.0
        frameCenterY = scene.imageHeight / 2.0

        # print scene.imageWidth

        self.offsetX = abs(frameCenterX - self.xcenter)
        self.offsetY = abs(frameCenterY - self.ycenter)

        percentVarianceX = (self.offsetX * 2.0 / frameCenterX) * 100
        self.manageOffsetHistory(percentVarianceX)

        distance = math.sqrt(abs(self.offsetX) ** 2 + abs(self.offsetY) ** 2)
        print "Distance: {}".format(distance)
        R = scene.imageHeight * 0.15
        if int(distance) <= R:
            self.isCentered = True
        else:
            print "Evalute func"
            MARGIN_Y = 0.05 * scene.imageHeight

            if self.ycenter > frameCenterY + MARGIN_Y:
                self.isFarUp = False
                self.isFarDown = True
            elif self.ycenter < frameCenterY - MARGIN_Y:
                self.isFarUp = True
                self.isFarDown = False
            else:
                self.isFarUp = False
                self.isFarDown = False

            if self.xcenter > frameCenterX:
                self.isFarRight = True
                self.isFarLeft = False
            elif self.xcenter < frameCenterX:
                self.isFarLeft = True
                self.isFarRight = False
            self.isCentered = False
        if self.debug_mode:
            print "****************"
            print "Center", self.isCentered
            print self.isFarLeft
            print self.isFarRight
            print self.isFarUp
            print self.isFarDown
            print "****************"

        return


class Camera():
    cvcamera = None
    cvreader = None
    width = 0
    height = 0
    panPos = 0
    tiltPos = 0
    zoomPos = -1
    _badPTZcount = 0

    def __init__(self, cfg, usbdevnum):
        # Start by establishing control connection
        pysca.connect(cfg['socket'])

        # Open video stream as CV camera
        # print usbdevnum
        self.cvcamera = cv2.VideoCapture(usbdevnum)
        self.width = int(self.cvcamera.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cvcamera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.cvreader = CameraReaderAsync.CameraReaderAsync(self.cvcamera)

    # def lostPTZfeed(self):
    #     return True
    #     # return False if self._badPTZcount < 5 else True
    #
    # def updatePTZ(self):
    #     self._badPTZcount += 1
    #     return

    # nowPanPos, nowTiltPos = pysca.get_pan_tilt_position()
    # nowZoomPos = pysca.get_zoom_position()
    #
    # if nowZoomPos < 0:
    #     self._badPTZcount += 1
    #     return/home/tungdv/Desktop/pycambot/cambot3.py
    #
    # self._badPTZcount = 0
    # print "P: {0:d} T: {1:d} Z: {2:d}".format( \
    #     nowPanPos, nowTiltPos, nowZoomPos)
    #
    # self.panPos = nowPanPos
    # self.tiltPos = nowTiltPos
    # self.zoomPos = nowZoomPos


class Stage():
    def __init__(self, cfg):
        self.homePan = cfg['homePan']
        self.homeTilt = cfg['homeTilt']
        self.homeZoom = cfg['homeZoom']
        self.maxLeftPan = cfg['maxLeftPan']
        self.maxRightPan = cfg['maxRightPan']
        self.trackingZoom = cfg['trackingZoom']
        self.trackingTiltAdjustment = cfg['trackingTiltAdjustment']


class Scene():
    homePauseTimer = None
    zoomTimer = None
    atHome = False
    subjectVolatile = True
    confidence = 0.01
    requestedZoomPos = -1

    # REVERSE = True

    def __init__(self, cfg, camera, stage):
        self.imageWidth = cfg["imageWidth"]
        self.imageHeight = cfg["imageHeight"]
        self.minConfidence = cfg["minConfidence"]
        self.returnHomeSpeed = cfg["returnHomeSpeed"]
        self.homePauseSeconds = cfg["homePauseSeconds"]

        self.homePauseTimer = RealtimeInterval(cfg["homePauseSeconds"], True)
        self.zoomTimer = RealtimeInterval(cfg["zoomMaxSecondsSafety"], True)

    def goHome(self, stage):
        pysca.pan_tilt(1, 0, 0, blocking=True)
        pysca.pan_tilt(1, self.returnHomeSpeed, self.returnHomeSpeed, stage.homePan, stage.homeTilt, blocking=True)
        pysca.set_zoom(1, stage.homeZoom, blocking=True)
        self.atHome = True
        self.requestedZoomPos = stage.homeZoom
        time.sleep(self.homePauseSeconds)

    def trackSubject(self, camera, stage, subject, face, faceCount):
        self.confidence = 100.0 / faceCount if faceCount else 0
        self.subjectVolatile = subject.isVolatile()
        # Should we stay in motion?
        if self.confidence < self.minConfidence \
                or not face.recentlyVisible \
                or subject.isCentered:
            # Stop all tracking motion
            print "Stop tracking motion"
            pysca.pan_tilt(1, 0, 0, blocking=True)
            return

        # Should we return to home position?
        if not face.recentlyVisible and not self.atHome:
            print 'Go Home'
            self.goHome(stage)
            return

        # Initiate no new tracking action unless face has been seen recently
        if not face.recentlyVisible:
            return

        # Adjust to tracking zoom and tilt (closer)
        # if subject.isCentered \
        #         and self.requestedZoomPos > 0 \
        #         and self.requestedZoomPos < stage.trackingZoom:
        #     pysca.pan_tilt(1, 0, 5, 0, stage.trackingTiltAdjustment, relative=True, blocking=True)
        #     pysca.set_zoom(1, stage.trackingZoom, blocking=True)
        #     self.requestedZoomPos = stage.trackingZoom

        SPEED = 10
        speed_x = SPEED
        speed_y = SPEED
        if subject.offsetX + subject.offsetY > 0:
            speed_x = SPEED * (subject.offsetX / (subject.offsetX + subject.offsetY))
            speed_y = SPEED * (subject.offsetY / (subject.offsetX + subject.offsetY))
        speed_x = round(speed_x, 0)
        speed_y = round(speed_y, 0)

        # if self.REVERSE:
        #     speed_x *= -1
        #     speed_y *= -1

        # print 'Speed_x is:\t{}\tSpeed_y is:\t{}'.format(speed_x, speed_y)
        if subject.isFarLeft:
            if subject.isFarUp:
                print "Object left up"
                pysca.pan_tilt(1, -speed_x, +speed_y)
            elif subject.isFarDown:
                print "Object left down"
                pysca.pan_tilt(1, -speed_x, -speed_y)
            else:
                "Object left"
                pysca.pan_tilt(1, -SPEED)
            print 'Speed_x is:\t{}\tSpeed_y is:\t{}'.format(speed_x, speed_y)
        elif subject.isFarRight:
            if subject.isFarUp:
                print "Object right up"
                pysca.pan_tilt(1, speed_x, +speed_y)
                pass
            elif subject.isFarDown:
                print "Object right down"
                pysca.pan_tilt(1, speed_x, -speed_y)
                pass
            else:
                print "Object right"
                pysca.pan_tilt(1, SPEED)
            print 'Speed_x is:\t{}\tSpeed_y is:\t{}'.format(speed_x, speed_y)
        self.atHome = False
        return


def printif(message):
    if g_debugMode:
        print message


def main(cfg):
    args["usbDeviceNum"] = 2
    camera = Camera(cfg['camera'], args["usbDeviceNum"])
    stage = Stage(cfg['stage'])
    subject = Subject(cfg['subject'])
    face = Face(cfg['face'])
    scene = Scene(cfg['scene'], camera, stage)

    fpsDisplay = True
    fpsCounter = WeightedFramerateCounter()
    fpsInterval = RealtimeInterval(10.0, False)
    scene.goHome(stage)
    # Loop on acquisition
    while 1:
        # camera.updatePTZ()
        raw = None
        raw = camera.cvreader.Read()

        if raw is not None:

            # This is the primary frame processing block
            fpsCounter.tick()

            raw = imutils.resize(raw, width=scene.imageWidth)
            gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)

            # ~ panMsg = "*" if camera.controller.panTiltOngoing() else "-"
            # ~ tiltMsg = "-"
            # ~ zoomMsg =  "*" if camera.controller.zoomOngoing() else "-"

            # ~ cv2.putText(raw, "P {} #{}".format(panMsg, camera.panPos), (5, 15),
            # ~ cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            # ~ cv2.putText(raw, "T {} #{}".format(tiltMsg, camera.tiltPos), (5, 45),
            # ~ cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            # ~ cv2.putText(raw, "Z {} #{}".format(zoomMsg, camera.zoomPos), (5, 75),
            # ~ cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # scan for faces here against a grayscale frame
            cascPath = "haarcascade_frontalface_default.xml"
            faceCascade = cv2.CascadeClassifier(cascPath)
            faces = faceCascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
                # flags = cv2.CV_HAAR_SCALE_IMAGE
            )

            # ~ printif("Found {0} faces!".format(len(faces)))
            if len(faces):
                (x, y, w, h) = faces[0]

                cv2.rectangle(raw, (x, y), (x + w, y + h), (255, 0, 0), 2)
                # cv2.imshow('img', raw)

                face.found(x + w / 2, y + h / 2)
                # (xcenter = x + w/2)
            else:
                face.lost()
            subject.evaluate(face, scene)
            scene.trackSubject(camera, stage, subject, face, len(faces))

            # ~ # Decorate the image with CV findings and camera stats
            # ~ cv2.putText(raw, subject.text(), (5, 105),
            # ~ cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # ~ for (x, y, w, h) in faces:
            # ~ cv2.rectangle(raw, (x, y), (x+w, y+h), (0, 255, 0), 2)

            # ~ # show the output image with decorations
            # ~ # (not easy to do on Docker)
            if g_debugMode:
                cv2.imshow("Output", raw)

        if fpsDisplay and fpsInterval.hasElapsed():
            print "{0:.1f} fps (processing)".format(fpsCounter.getFramerate())
            # ~ if camera.cvreader is not None:
            # ~ print "{0:.1f} fps (camera)".format(camera.cvreader.fps.getFramerate())
            print "Face has been seen for {0:.1f} seconds".format(face.age())

        # Monitor for control keystrokes in debug mode
        if g_debugMode:
            keyPress = cv2.waitKey(1)
            if keyPress != -1:
                keyPress = keyPress & 0xFF
            if keyPress == ord("q"):
                break
    # Clean up
    printif("Cleaning up")
    if camera.cvreader is not None:
        camera.cvreader.Stop()
        time.sleep(0.5)
    if camera.cvcamera is not None:
        camera.cvcamera.release()
    if g_debugMode:
        cv2.destroyAllWindows()

    printif("End of main function")


# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser(description="OpenCV camera operation robot")
ap.add_argument("--usb", dest="usbDeviceNum", type=int, action="store", default=0,
                help="USB device number; USB device 0 is the default camera")
ap.add_argument("--stream", type=str, action="store",
                help="optional stream context, appended to IP and used instead of USB for CV frame reads")
ap.add_argument("--release", dest="releaseMode", action="store_const", const=True, default=not g_debugMode,
                help="hides all debug windows (default: False)")
args = vars(ap.parse_args())

#

g_debugMode = not args["releaseMode"]

with open("config.json", "r") as configFile:
    cfg = json.load(configFile)

main(cfg)
exit()
