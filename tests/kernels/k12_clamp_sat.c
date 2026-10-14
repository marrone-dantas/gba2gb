/* Soma com saturação de 16 bits com sinal */
int f(int r0,int r1,int r2,int r3){ int a=(short)r0, b=(short)r1, s=a+b; if(s>32767)s=32767; if(s<-32768)s=-32768;
 int t=(signed char)r2 + (signed char)r3; if(t>127)t=127; if(t<-128)t=-128; return (s<<8)^t; }
