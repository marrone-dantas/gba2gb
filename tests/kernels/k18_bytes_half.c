/* Signed/unsigned byte and halfword accesses on the stack */
int f(int r0,int r1,int r2,int r3){ volatile unsigned buf[2]; buf[0]=r0; buf[1]=r1;
 volatile unsigned char *b=(volatile unsigned char*)buf; volatile short *h=(volatile short*)buf; volatile signed char *sb=(volatile signed char*)buf;
 b[r2&7]=r3; h[(r3>>8)&3]=r2;
 return b[1]+h[0]+sb[2]+ (unsigned short)h[3] + sb[(r2>>4)&7] + buf[1]; }
