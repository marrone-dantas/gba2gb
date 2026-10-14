/* Audio is not ported: maxmod calls are no-ops. */
#ifndef COMPAT_MAXMOD_H
#define COMPAT_MAXMOD_H
typedef unsigned int mm_addr;
#define mmVBlank 0
#define mmInitDefault(a,b) ((void)0)
#define mmSetModuleVolume(v) ((void)0)
#define mmSetJingleVolume(v) ((void)0)
#define mmFrame() ((void)0)
#define mmStart(a,b) ((void)0)
#define mmStop() ((void)0)
#define mmPause() ((void)0)
#define mmResume() ((void)0)
#define mmEffect(n) ((void)0)
#endif
