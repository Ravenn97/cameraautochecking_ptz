import numpy as np
from cv2 import cv2
from imutils import face_utils
import imutils
import math
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

# Tunable parameters

g_debugMode = True
g_testImage = None


class Face():
    _recentThresholdSeconds = 0

    visible = False
    didDisappear = False
    recentlyVisible = False
    lastSeenTime = 0
    firstSeenTime = 0
    hcenter = -1

    def __init__(self, cfg):
        self._recentThresholdSeconds = cfg["recentThresholdSeconds"]

    def found(self, hcenter, vcenter):
        now = time.time()
        if not self.visible:
            self.firstSeenTime = now
        self.lastSeenTime = now

        self.hcenter = hcenter
        self.vcenter = vcenter
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
            return now - self.firstSeenTimerecentlyVisible
        else:
            return 0


class Subject():
    hcenter = -1
    off_X_set = 1
    off_Y_set = 1
    offsetHistory = []
    isPresent = False
    isCentered = True
    isFarLeft = False
    isFarRight = False
    isFarUp = False
    isFarDown = False

    def __init__(self):
        pass

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
        # type prior and current is tuple
        try:
            while True:
                deltas.append(abs(current - prior))
                prior = current
                current = history.next()
        except StopIteration:
            pass
        avgDelta = float(sum(deltas) / len(deltas))
        return True if avgDelta > 10 else False

    def evaluate(self, face, scene):
        if not face.visible:
            if not face.recentlyVisible:
                # If we haven't seen a face in a while, reset
                self.hcenter = -1
                self.off_X_set = 0
                self.isPresent = False
                self.isCentered = True
                self.isFarLeft = False
                self.isFarRight = False
                self.isFarDown = False
                self.isFarUp = False
            ################################################
            # If we still have a recent subject location, keep it
            self.isPresent = True
            return

        # We have a subject and can characterize location in the frame 
        self.isPresent = True
        self.hcenter = face.hcenter
        frame_X_Center = scene.imageWidth / 2.0
        ###################################################
        self.vcenter = face.vcenter
        frame_Y_Center = scene.imageHeight / 2.0

        self.off_Y_set = frame_Y_Center - self.vcenter
        ##################################################
        self.off_X_set = frame_X_Center - self.hcenter

        # percent_X_Variance = (self.off_X_set * 2.0 / frame_X_Center) * 100
        # percent_Y_Variance = (self.off_Y_set * 2.0 / frame_Y_Center) * 100

        the_distance = math.sqrt(self.off_X_set ** 2 + self.off_Y_set ** 2)
        ######################################
        self.manageOffsetHistory(the_distance)
        #########################
        the_center = (self.hcenter, self.vcenter)
        the_radius = int(1 / 6 * scene.imageHeight)

        if the_distance <= the_radius:
            self.isCentered = True
            self.isFarLeft = False
            self.isFarRight = False
            self.isFarUp = False
            self.isFarDown = False
        else:
            self.isCentered = False
            if self.hcenter < frame_X_Center and self.vcenter < frame_Y_Center:
                self.isFarLeft = True
                self.isFarUp = True
            if self.hcenter < frame_X_Center and self.vcenter > frame_Y_Center:
                self.isFarLeft = True
                self.isFarDown = True
            if self.hcenter > frame_X_Center and self.vcenter < frame_Y_Center:
                self.isFarRight = True
                self.isFarDown = True
            if self.hcenter > frame_X_Center and self.vcenter > frame_Y_Center:
                self.isFarRight = True
                self.isFarUp = True

        return

    # def text(self):
    #     msg = "Subj: "
    #     msg += "! " if self.isVolatile() else "- "
    #     if not self.isPresent:
    #         msg += "..."
    #         return msg
    #     if not self.isCentered and not self.isFarLeft and not self.isFarRight:
    #         msg += "oOo"
    #     if self.isCentered:
    #         msg += ".|."
    #     if self.isFarLeft:
    #         msg += "<.."
    #     if self.isFarRight:
    #         msg += "..>"
    #     return msg


class Camera():
    cvcamera = None
    cvreader = None
    width = 0
    height = 0
    panPos = 0
    tiltPos = 0
    zoomPos = -1

    def __init__(self, cfg, usbdevnum):
        # Start by establishing control connection
        pysca.connect(cfg['socket'])

        # Open video stream as CV camera
        # print usbdevnum
        self.cvcamera = cv2.VideoCapture(usbdevnum)
        self.width = int(self.cvcamera.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cvcamera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.cvreader = CameraReaderAsync.CameraReaderAsync(self.cvcamera)

        # nowPanPos, nowTiltPos = pysca.get_pan_tilt_position()
        # nowZoomPos = pysca.get_zoom_position()
        #
        # if nowZoomPos < 0:
        #     self._badPTZcount += 1
        #     return
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
        self.trackingZoom = cfg['trackingZoom']


class Scene():
    homePauseTimer = None
    zoomTimer = None
    atHome = False
    subjectVolatile = True
    confidence = 0.01
    requestedZoomPos = -1
    score_x_y = 1
    speed_X = 2
    speed_y = 2

    def __init__(self, cfg, camera, stage):
        self.imageWidth = cfg["imageWidth"]
        self.imageHeight = cfg["imageHeight"]
        self.minConfidence = cfg["minConfidence"]
        self.returnHomeSpeed = cfg["returnHomeSpeed"]
        self.homePauseSeconds = cfg["homePauseSeconds"]

        self.homePauseTimer = RealtimeInterval(cfg["homePauseSeconds"], False)
        self.zoomTimer = RealtimeInterval(cfg["zoomMaxSecondsSafety"], False)

    def goHome(self, camera, stage):
        pysca.pan_tilt(1, 0, 0, blocking=True)
        pysca.pan_tilt(1, self.returnHomeSpeed, self.returnHomeSpeed, stage.homePan, stage.homeTilt, blocking=True)
        pysca.set_zoom(1, stage.homeZoom, blocking=True)
        self.atHome = True
        self.requestedZoomPos = stage.homeZoom
        time.sleep(self.homePauseSeconds)

    def trackSubject(self, camera, stage, subject, face, faceCount):
        self.confidence = 100.0 / faceCount if faceCount else 0
        self.subjectVolatile = subject.isVolatile()
        self.score_x_y = abs(subject.off_Y_set) / (abs(subject.off_X_set) + 0.001)
        if self.score_x_y - int(self.score_x_y) >= 0.5:
            self.score_x_y = int(self.score_x_y) + 1
        self.speed_y = self, speed_x * self.score_x_y

        # Should we stay in motion?
        if faceCount != 1 \
                or not face.recentlyVisible \
                or self.subjectVolatile \
                or subject.isCentered:
            # Stop all tracking motion
            pysca.pan_tilt(1, 0, 0, blocking=True)

        # Should we return to home position?
        if not face.recentlyVisible \
                and not self.atHome:
            self.goHome(camera, stage)
            return

        # Initiate no new tracking action unless face has been seen recently

        # if not face.recentlyVisible:
        #     return

        # Adjust to tracking zoom and tilt (closer)
        if subject.isCentered \
                and not self.subjectVolatile \
                and self.requestedZoomPos > 0 \
                and self.requestedZoomPos < stage.trackingZoom:
            pysca.set_zoom(1, stage.trackingZoom, blocking=True)
            self.requestedZoomPos = stage.trackingZoom
        else:
            # dang tinh ti so giua khoang cach x va y de tinh toc do giua x va y
            if subject.isFarLeft and subject.isFarUp:
                self.speed_X = - self.speed_X
                self.speed_y = self.speed_y
            if subject.isFarLeft and subject.isFarDown:
                self.speed_X = - self.speed_X
                self.speed_y = - self.speed_y
            elif subject.isFarRight and subject.isFarUp:
                self.speed_X = self.speed_X
                self.speed_y = self.speed_y
            elif subject.isFarRight and subject.isFarDown:
                self.speed_X = self.speed_X
                self.speed_y = -self.speed_y

            pysca.pan_tilt(1, self.speed_X, self.speed_y)
        self.atHome = False
        return


def printif(message):
    if g_debugMode:
        print message


def main(cfg):
    args["usbDeviceNum"] = 0
    camera = Camera(cfg['camera'], args["usbDeviceNum"])
    stage = Stage(cfg['stage'])
    subject = Subject()
    face = Face(cfg['face'])
    scene = Scene(cfg['scene'], camera, stage)

    fpsDisplay = True
    fpsCounter = WeightedFramerateCounter()
    fpsInterval = RealtimeInterval(10.0, False)

    # Loop on acquisition
    while 1:
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
                face.found(x + w / 2, y + h / 2)
                # (hcenter = x + w/2)
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
        scene.goHome(camera, stage)
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
