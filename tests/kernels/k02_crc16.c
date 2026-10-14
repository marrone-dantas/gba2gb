/* CRC-16/CCITT sobre os 16 bytes de r0..r3 */
int f(int r0,int r1,int r2,int r3){ unsigned w[4]={r0,r1,r2,r3}; unsigned crc=0xFFFF;
 for(int i=0;i<16;i++){ crc^=((w[i>>2]>>((i&3)*8))&0xFF)<<8;
  for(int b=0;b<8;b++) crc = (crc&0x8000)?((crc<<1)^0x1021):(crc<<1); crc&=0xFFFF; }
 return crc; }
