/* AABB collision: boxes packed into 16 bits (8-bit x,y,w,h) */
int f(int r0,int r1,int r2,int r3){ int ax=r0&255,ay=(r0>>8)&255,aw=(r1&15)+1,ah=((r1>>4)&15)+1;
 int bx=r2&255,by=(r2>>8)&255,bw=(r3&15)+1,bh=((r3>>4)&15)+1;
 return (ax<bx+bw)&&(bx<ax+aw)&&(ay<by+bh)&&(by<ay+ah); }
