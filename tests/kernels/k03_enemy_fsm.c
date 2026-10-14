/* Enemy state machine: patrol/chase/attack/flee for 16 steps */
int f(int r0,int r1,int r2,int r3){ int st=r0&3, x=r1&255, px=r2&255, hp=(r3&31)+1, i;
 for(i=0;i<16;i++){ int d=px-x; if(d<0)d=-d;
  if(st==0){ x+=(i&4)?1:-1; if(d<40)st=1; }
  else if(st==1){ x+= (px>x)?2:-2; if(d<8)st=2; else if(hp<5)st=3; }
  else if(st==2){ hp-=3; if(hp<5)st=3; else if(d>=8)st=1; }
  else { x+=(px>x)?-3:3; hp++; if(hp>20)st=0; }
  px += (r3>>i)&1 ? 1 : -1; }
 return (st<<24)|((hp&255)<<16)|(x&0xFFFF); }
