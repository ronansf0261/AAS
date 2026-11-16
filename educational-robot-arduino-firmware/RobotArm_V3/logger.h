#ifndef LOGGER_H_
#define LOGGER_H_

#include <Arduino.h>

#define LOG_ERROR 0
#define LOG_INFO 1
#define LOG_DEBUG 2
#define LOG_TRACE 3

class Logger {
  public:
    static void log(String message, int level);
    static void logINFO(String message);
    static void logERROR(String message);
    static void logDEBUG(String message);
    static void logTRACE(String message);
};
#endif
