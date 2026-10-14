/* lockstep kernel for __aeabi_lmul (tests/test_softfloat.py) */
typedef unsigned u32; typedef unsigned long long u64;
#define F __aeabi_lmul
#define J(lo,hi) (((u64)(hi)<<32)|(lo))
u64 F(u64,u64);
u64 f(u32 a,u32 b,u32 c,u32 d){return F(J(a,b),J(c,d));}
