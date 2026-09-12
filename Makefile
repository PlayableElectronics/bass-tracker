# Project Name
TARGET = BassAnalyzer

# Sources
CPP_SOURCES = BassAnalyzer.cpp PitchDetector.cpp PitchTracker.cpp EnvelopeFollower.cpp \
	ExpressionBus.cpp ExpressionCalibration.cpp ExpressionMidiProtocol.cpp ModulationMatrix.cpp

# Default remains USB CDC logging. Set EXPRESSION_USB_MIDI=1 for the optional
# WebMIDI control/telemetry endpoint; libDaisy exposes CDC and MIDI as mutually
# exclusive USB descriptors, so this mode deliberately replaces CDC at build time.
EXPRESSION_USB_MIDI ?= 0
C_DEFS += -DBASS_EXPRESSION_USB_MIDI=$(EXPRESSION_USB_MIDI)

# Library Locations
LIBDAISY_DIR = ../../DaisyExamples/libDaisy
DAISYSP_DIR = ../../DaisyExamples/DaisySP

# Include floating-point formatting support in libDaisy's logger.
LDFLAGS = -u _printf_float

SYSTEM_FILES_DIR = $(LIBDAISY_DIR)/core
include $(SYSTEM_FILES_DIR)/Makefile
