# Project Name
TARGET = BassAnalyzer

# Sources
CPP_SOURCES = BassAnalyzer.cpp

# Library Locations
LIBDAISY_DIR = ../../DaisyExamples/libDaisy
DAISYSP_DIR = ../../DaisyExamples/DaisySP

# Include floating-point formatting support in libDaisy's logger.
LDFLAGS = -u _printf_float

SYSTEM_FILES_DIR = $(LIBDAISY_DIR)/core
include $(SYSTEM_FILES_DIR)/Makefile
