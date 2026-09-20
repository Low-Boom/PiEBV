/****************************************************************************************************************************
  derived from PWM_Multi.ino

  For Teensy boards (Teensy 2.x, Teensy LC, Teensy 3.x, Teensy 4.x, etc.)
  Written by Khoi Hoang

  Built by Khoi Hoang https://github.com/khoih-prog/Teensy_PWM
  Licensed under MIT license
*****************************************************************************************************************************/

#define _PWM_LOGLEVEL_       4
// Teensy_PWM (v1.1.1)
#include "Teensy_PWM.h"
// to allow PWM frequencies below 17.8 Hz use Teensy_Slow_PWM (v1.2.1)
//#include "Teensy_Slow_PWM.h"
// TeensyTimerTool (v1.4.1)
#include "TeensyTimerTool.h"
// SimpleSerialShell (1.0.0)
#include <SimpleSerialShell.h>

#define BAUDRATE 115200

#define USING_FLEX_TIMERS      true

// To select correct pins from different timers for different frequencies
// For example, pin 7/FlexPWM1_3_B and pin8/FlexPWM1_3_A will have same frequency, etc.
// For the whole list, check Teensy_PWM.h or README.md

#if USING_FLEX_TIMERS
// Using FlexTimers
//uint32_t PWM_Pins[] = { 4, 5, 6, 7 };
uint32_t g_PWM_Pins[] = { 4, 6 };
#else
// Using QuadTimers
uint32_t g_PWM_Pins[] = { 10, 11, 14, 15 };
#endif


int32_t g_pulseDelayNanos = 10000;    // time between both laser pulses in [ns]
int32_t g_pulseWidthNanos = 2000;     // width of each laser pulse in [ns]
float g_pulsePeriodMicros = 1000.;    // period of laser double-pulses in [usec]
//float g_pulseFrequencyHz = 1000.;   // frequency of laser double-pulses in [Hz] (1/period)
float g_syncFrequencyHz = 1000000.0;  // 1 MHz camera sync.
float g_refMarkerFrequencyHz = 25.;   // 25 Hz reference markers, stable for multiples of 25
// with TeensyPWM: maximum interval / frequency is 55922.3467 us --> 17.881939 Hz
float g_refMarkerDutyCycle = 0.1f;    // with 40 usec pulse width

float g_PWM_frequency[]   = { g_syncFrequencyHz, g_refMarkerFrequencyHz };
float g_PWM_dutyCycle[]   = { 50.0f, g_refMarkerDutyCycle }; // in percent!

int32_t g_pulseState = 0;
int32_t g_pulseCnt   = 0;
int32_t g_pulseSkip  = 100;

#define NUM_OF_PINS   ( sizeof(g_PWM_Pins) / sizeof(uint32_t) )
#define _PULSE_OUT_CH1  2
#define _PULSE_OUT_CH2  3
#define _PULSE_OUT_REF  5
#define _LED_PIN13      13

char doubleDashLine[] = ("=====================================================================================");
char singleDashLine[] = ("-------------------------------------------------------------------------------------");

Teensy_PWM* g_PWM_Instance[NUM_OF_PINS];

TeensyTimerTool::PeriodicTimer timer_t1(TeensyTimerTool::GPT1);  // First channel on TMR1 aka QUAD timer module. (TMR1 - TMR4, four 16bit channels each)

static inline void _delayNanoseconds(uint32_t nsec)
{
  uint32_t begin = ARM_DWT_CYCCNT;
  uint32_t cycles =   ((F_CPU_ACTUAL>>16) * nsec) / (1000000000UL>>16);
  while (ARM_DWT_CYCCNT - begin < cycles) ; // wait
}


/*void pulse500ns()
{
    digitalWriteFast(_PULSE_OUT_CH1, HIGH);
    delayNanoseconds(500);
    digitalWriteFast(_PULSE_OUT_CH1, LOW);
} */

void togglePulse()
{
  digitalWriteFast(_PULSE_OUT_REF, g_pulseState ? HIGH : LOW);
  g_pulseState = !g_pulseState;
}

void doublePulse500ns()
{
  // could be optimized to run faster/ more accurate
  // todo: figure out reqd time to call these fxns
 
  digitalWriteFast(_LED_PIN13, HIGH);
  if(g_pulseCnt == 0)
    digitalWriteFast(_PULSE_OUT_REF, HIGH);

  int32_t t_pw = g_pulseWidthNanos - 25;
  int32_t t_pd = g_pulseDelayNanos - 25;
  if(t_pw <= 0) {
      digitalWriteFast(_PULSE_OUT_CH1, HIGH);
      digitalWriteFast(_PULSE_OUT_CH2, HIGH);
      delayNanoseconds(t_pw); // skip
      digitalWriteFast(_PULSE_OUT_CH1, LOW);
      digitalWriteFast(_PULSE_OUT_CH2, LOW);
  }
  
  else if (t_pd < t_pw) {
    int32_t t_diff = t_pw - t_pd;
    digitalWriteFast(_PULSE_OUT_CH1, HIGH);
    delayNanoseconds(t_pd);
    digitalWriteFast(_PULSE_OUT_CH2, HIGH);
    delayNanoseconds(t_diff);
    digitalWriteFast(_PULSE_OUT_CH1, LOW);
    delayNanoseconds(t_pd);
    digitalWriteFast(_PULSE_OUT_CH2, LOW);
   }
   else if (t_pd == t_pw) {
    digitalWriteFast(_PULSE_OUT_CH1, HIGH);
    delayNanoseconds(t_pw);
    digitalWriteFast(_PULSE_OUT_CH2, HIGH);
    //delayNanoseconds(t_diff); // skip
    digitalWriteFast(_PULSE_OUT_CH1, LOW);
    delayNanoseconds(t_pw);
    digitalWriteFast(_PULSE_OUT_CH2, LOW);
 }
   else {
    int32_t t_diff = g_pulseDelayNanos - g_pulseWidthNanos - 25;
    
    digitalWriteFast(_PULSE_OUT_CH1, HIGH);
    delayNanoseconds(t_pw);
    digitalWriteFast(_PULSE_OUT_CH1, LOW);
    delayNanoseconds(t_diff);
    digitalWriteFast(_PULSE_OUT_CH2, HIGH);
    delayNanoseconds(t_pw);
    digitalWriteFast(_PULSE_OUT_CH2, LOW);
  }

  if(g_pulseCnt == 0)
    digitalWriteFast(_PULSE_OUT_REF, LOW);
  digitalWriteFast(_LED_PIN13, LOW);

  g_pulseCnt++;
  if(g_pulseCnt >= g_pulseSkip)
    g_pulseCnt = 0;
}

/**
 * @brief Checks to see if a character is in a string.
 *
 * @param needle The character being searched for
 * @param haystack null-delimited string
 * @return true If found.
 */
static bool isIn(char needle, const char* haystack) {
  const char* ptr = haystack;
  while (*ptr != 0) {
    if (needle == *ptr) {
      return true;
    }
    ptr++;
  }
  return false;
}

/**
 * @brief The tokenizer function that conforms to the SimpleSerialShell signature
 * requirement.  Please see strtok_r(3) for an explanation of the expected semantics.
 * 
 * @param str 
 * @param delims 
 * @param saveptr 
 * @return char* 
 */

/**
 * @brief Installed into the shell as a command processor.  Prints out the 
 * arguments passed to the function.
 * 
 * @param argc 
 * @param argv 
 * @return int 
 */
int echo(int argc, char **argv) { 
    for (int i = 1; i < argc; i++) {
        shell.print("Argument ");
        shell.print(i);
        shell.print(": [");
        shell.print(argv[i]);
        shell.println("]");
    }
    return 0;
}

////////////////////////////////////////////////////////////////////////////////
// Forgot what sketch was loaded to this board?
//
// Hint1: use the F() macro to keep const strings in FLASH and save RAM
// Hint2: "Compiler " "catenates consecutive "
//         "strings together"
//         (improves readability for very long strings)
//
int showID(int /*argc*/ = 0, char** /*argv*/ = NULL)
{
    shell.println(F( "Running " __FILE__ ",\nBuilt " __DATE__));
    return 0;
};

// send back compact string of current configuration
int showConfig(int /*argc*/ = 0, char** /*argv*/ = NULL)
{
  double freq = 1000000.0/g_pulsePeriodMicros;
  shell.printf(
    "f %g;pd %g;pw %g;\n",
     freq, 
    (float)g_pulseDelayNanos/1000,
    (float)g_pulseWidthNanos/1000
    );
    return 0;
};

// print info on current configuration
int printStatus(int /*argc*/ = 0, char** /*argv*/ = NULL)
{
  shell.println(F(doubleDashLine));
  shell.printf(" Laser pulse 1 on pin %d\n", _PULSE_OUT_CH1);
  shell.printf(" Laser pulse 2 on pin %d\n", _PULSE_OUT_CH2);
  shell.printf(
    "    pulse freq       %g Hz\n"
    "    pulse width      %g usec\n"
    "    pulse 1-2 delay  %g usec\n"
    "   Note: actual pulse delays/widths may differ! (Verify via scope)\n"
    ,
    1000000.0/g_pulsePeriodMicros, 
    (float)g_pulseWidthNanos/1000,
    (float)g_pulseDelayNanos/1000
    );
  float refMarkerFreq = 1e6 / (g_pulsePeriodMicros * g_pulseSkip);
  shell.printf( "   Reference marker at %g Hz\n", refMarkerFreq );
  shell.println(F(singleDashLine));
  // for (uint8_t index = 0; index < NUM_OF_PINS; index++)
  //  printPWMInfo(g_PWM_Instance[index]);
  printPWMInfo(g_PWM_Instance[0]);
  shell.println(F(doubleDashLine));
  return 0;
};

int setPulseDelay(int argc, char **argv)
{
    if (argc != 2) {
        shell.println("setPulseDelay() - bad argument count");
        return -1;
    }
    float dt = atof(argv[1]);
    if(dt < 0) {
      shell.printf("setPulseDelay() - Invalid pulse delay: %g us\n", dt);
      return EXIT_FAILURE;
    }
    g_pulseDelayNanos = int32_t(dt*1000);
    shell.printf("Setting double pulse separation to %d ns\n", g_pulseDelayNanos);
    //shell.print(g_pulseDelayNanos);
    //.println("ns");

    return EXIT_SUCCESS;
}

int setPulseWidth(int argc, char **argv)
{
    if (argc != 2) {
        shell.println("setPulseWidth() - bad argument count");
        return -1;
    }
    float dt = atof(argv[1]);
    if(dt < 0.5) {
      shell.printf("setPulseWidth() - Invalid pulse width: %g us\n", dt);
      return EXIT_FAILURE;
    }
    g_pulseWidthNanos = int32_t(dt*1000);
    shell.printf("Setting pulse width to %d ns\n", g_pulseWidthNanos);

    return EXIT_SUCCESS;
}

int setPulseFrequency(int argc, char **argv)
{
    if (argc != 2) {
        shell.println("setPulseFrequency() - bad argument count");
        return -1;
    }
    float freq = atof(argv[1]);
    if((freq < 0.5) || (freq > 50000)) {
      shell.printf("setPulseFrequency() - Invalid pulse frequency: %g us", freq);
      shell.println(F("Valid range [0.5 ... 50'000]"));
      return EXIT_FAILURE; // restarts
    }
    g_pulsePeriodMicros = 1000000.0/freq;
    timer_t1.setPeriod(g_pulsePeriodMicros);
    shell.printf("Setting pulse frequency to %g Hz\n", freq);

    return EXIT_SUCCESS;  
}

int setSyncSkip(int argc, char **argv)
{
    if (argc != 2) {
        shell.println("setSyncSkip() - bad argument count");
        return -1;
    }
    int32_t nSkip = atoi(argv[1]);
    if((nSkip < 1)) {
      shell.printf("Invalid sync skip: %d", nSkip);
      shell.println(F("Valid range [1 ... 20'000]"));
      return -1; //EXIT_FAILURE;
    }
    float refMarkerFreq = 1e6 / (g_pulsePeriodMicros * nSkip);
    shell.printf("Setting sync out period to %g Hz (skip=%d)\n", 
      refMarkerFreq, nSkip
    );
    g_pulseSkip = nSkip;

    return EXIT_SUCCESS;  
}

int setSyncOut(int argc, char **argv)
{
    shell.println("setSyncOut() - not implemented");
    return 0;

    if (argc != 3) {
        shell.println("setSyncOut() - bad argument count");
        return -1;
    }
    float freq = atof(argv[1]);
    float duty = atof(argv[2]);
    if((freq < 1) || (freq > 50000)) {
      shell.printf("Invalid sync frequency: %g us", freq);
      shell.println(F("Valid range [1 ... 50'000]"));
      return EXIT_FAILURE;
    }
    g_refMarkerFrequencyHz = freq;
    g_refMarkerDutyCycle = duty;
    float period_us = 1'000'000.0 / freq;
    shell.printf("Setting sync out frequency %g Hz (duty = %g%%)\n", 
      g_refMarkerFrequencyHz, g_refMarkerDutyCycle
    );
    if(g_PWM_Instance[1]) {
      g_PWM_Instance[1]->setPWM_Period(
        g_PWM_Instance[1]->getPin(), period_us, g_refMarkerDutyCycle
      );
    }

    return EXIT_SUCCESS;
}


void printPWMInfo(Teensy_PWM* PWM_Instance)
{
  float freq = PWM_Instance->getActualFreq();
  float period_usec = 1'000'000.0 / freq;
  float pwm_width = PWM_Instance->getActualDutyCycle() * period_usec * 0.01;
  shell.printf(" PWM on pin %d:", PWM_Instance->getPin());
  shell.printf("  Freq: %10.2f Hz", PWM_Instance->getActualFreq());
  shell.printf("  duty: %5.2f%% (%g usec)\n", PWM_Instance->getActualDutyCycle(), pwm_width);
}


void setup()
{
  pinMode(_PULSE_OUT_CH1, OUTPUT);
  pinMode(_PULSE_OUT_CH2, OUTPUT);
  pinMode(_LED_PIN13, OUTPUT);
  pinMode(_PULSE_OUT_REF, OUTPUT);
  
  timer_t1.begin(doublePulse500ns, g_pulsePeriodMicros); // fire double-pulses at given frequency
  
  Serial.begin(BAUDRATE);
  shell.attach(Serial);
  //shell.setTokenizer(tokenizer);
  shell.addCommand(F("f <Hz>            - set pulsing freqeuncy"), setPulseFrequency);
  shell.addCommand(F("pf <Hz>           - set pulsing freqeuncy"), setPulseFrequency);
  shell.addCommand(F("pd <microseconds> - set pulse 1-2 delay"), setPulseDelay);
  shell.addCommand(F("pw <microseconds> - set pulse width"), setPulseWidth);
  //shell.addCommand(F("ref <Hz> <duty>   - set reference pulse freq and duty cycle"), setSyncOut);
  shell.addCommand(F("ref <skip>        - set reference pulse interval multiple of pulse period"), setSyncSkip);
  shell.addCommand(F("i                 - show current configuration"), showConfig);
  shell.addCommand(F("?                 - print status"), printStatus);
  shell.addCommand(F("id?               - info on installed firmware"), showID);  
  
  while (!Serial && millis() < 1000);

  delay(1500);

#if USING_FLEX_TIMERS
  Serial.print(F("\nStarting PWM_Multi using FlexTimers on "));
#else
  Serial.print(F("\nStarting PWM_Multi using QuadTimers on "));
#endif

  Serial.println(BOARD_NAME);
  Serial.println(TEENSY_PWM_VERSION);

  for (uint8_t index = 0; index < NUM_OF_PINS; index++)
  {
    g_PWM_Instance[index] = new Teensy_PWM(
      g_PWM_Pins[index], 
      g_PWM_frequency[index], 
      g_PWM_dutyCycle[index]
      );

    if (g_PWM_Instance[index])
    {
      g_PWM_Instance[index]->setPWM();
    }
  }

  Serial.println(doubleDashLine);
  Serial.println("Index\tPin\tPWM_freq\tDutyCycle\tActual Freq");
  Serial.println(singleDashLine);

  for (uint8_t index = 0; index < NUM_OF_PINS; index++)
  {
    if (g_PWM_Instance[index])
    {
      Serial.print(index);
      Serial.print("\t");
      Serial.print(g_PWM_Pins[index]);
      Serial.print("\t");
      Serial.print(g_PWM_frequency[index]);
      Serial.print("\t\t");
      Serial.print(g_PWM_dutyCycle[index]);
      Serial.print("\t\t");
      Serial.println(g_PWM_Instance[index]->getActualFreq(), 4);
    }
    else
    {
      Serial.println();
    }
  }
  Serial.println(doubleDashLine);

  for (uint8_t index = 0; index < NUM_OF_PINS; index++)
  {
    printPWMInfo(g_PWM_Instance[index]);
  }

  Serial.println(
    F("Terminate input commands with a semicolon ';'"
    "\nNote: actual pulse delays/widths may differ! (Verify via scope)"
    ));
  Serial.println(F("Type 'help;' - for more info"));
}

void loop()
{
  shell.executeIfInput();
  //Long delay has no effect on the operation of hardware-based PWM channels
  //delay(1000000);
}
