/* lockstep kernel for __aeabi_f2d (tests/test_softfloat.py) */
typedef unsigned u32; typedef unsigned long long u64;
#define F __aeabi_f2d
#define J(lo,hi) (((u64)(hi)<<32)|(lo))
u64 F(u32);
u64 f(u32 a){return F(a);}
