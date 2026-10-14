/* 8.8 fixed-point physics: position/velocity/gravity with bounce */
int f(int r0,int r1,int r2,int r3){ int y=(r0&0x7FFF), vy=(short)r1>>4, g=(r2&63)+1, bounces=0;
 for(int i=0;i<20;i++){ vy+=g; y+=vy; if(y>0x6000){ y=0x6000; vy=-(vy*3>>2); bounces++; } if(y<0)y=0; }
 return (y<<8)|(bounces&255)|((vy&0xFF)<<24); }
