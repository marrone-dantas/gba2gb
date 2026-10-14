// fix16.hpp - 16.16 fixed-point drop-in for `float` in homebrew sources (gba2gb
// float->fixed source transform, tools/fixpt/float2fix.py). PICO-8 itself computes in
// 16.16 fixed point, so ports of PICO-8 games keep their original number model.
//
// Cost model on the SM83 target: add/sub/compare are 32-bit integer ops; products use
// (a>>8)*(b>>8) (8 fractional bits per operand, one 32-bit multiply) unless one side is a
// compile-time integer; divisions by compile-time constants become (a*num)/den with the
// reduced fraction 65536/b, so no 64-bit helper is needed.
#ifndef GBA2GB_FIX16_HPP
#define GBA2GB_FIX16_HPP
#include <stdint.h>
// freestanding C++ hides parts of <stdlib.h>; the C library helpers used by homebrew
extern "C" int rand(void);
extern "C" void srand(unsigned);

struct fix16 {
    int32_t v;
    fix16() = default;
    static constexpr fix16 raw(int32_t r) { fix16 f{}; f.v = r; return f; }
    constexpr fix16(int i) : v((int32_t)((uint32_t)i << 16)) {}
    constexpr fix16(unsigned i) : v((int32_t)(i << 16)) {}
    constexpr fix16(long i) : v((int32_t)((uint32_t)i << 16)) {}
    constexpr fix16(unsigned long i) : v((int32_t)((uint32_t)i << 16)) {}
    constexpr fix16(short i) : v((int32_t)((uint32_t)(int)i << 16)) {}
    constexpr fix16(unsigned short i) : v((int32_t)((uint32_t)i << 16)) {}
    constexpr fix16(signed char i) : v((int32_t)((uint32_t)(int)i << 16)) {}
    constexpr fix16(unsigned char i) : v((int32_t)((uint32_t)i << 16)) {}
    constexpr fix16(char i) : v((int32_t)((uint32_t)(int)i << 16)) {}
    constexpr fix16(bool b) : v(b ? 65536 : 0) {}
    // C float->integer conversion truncates toward zero
    constexpr int toint() const { return v >= 0 ? (v >> 16) : -((-v) >> 16); }
    constexpr operator int() const { return toint(); }
    constexpr fix16 operator-() const { return raw(-v); }
    constexpr fix16 operator+() const { return *this; }
    fix16 &operator+=(fix16 b) { v += b.v; return *this; }
    fix16 &operator-=(fix16 b) { v -= b.v; return *this; }
    fix16 &operator*=(fix16 b);
    fix16 &operator/=(fix16 b);
    fix16 &operator++() { v += 65536; return *this; }
    fix16 &operator--() { v -= 65536; return *this; }
};


static inline __attribute__((always_inline)) fix16 fix16_mul(fix16 a, fix16 b)
{
    if (__builtin_constant_p(b.v) && (b.v & 0xFFFF) == 0)
        return fix16::raw(a.v * (b.v >> 16));
    if (__builtin_constant_p(a.v) && (a.v & 0xFFFF) == 0)
        return fix16::raw(b.v * (a.v >> 16));
    return fix16::raw((a.v >> 8) * (b.v >> 8));
}

static inline __attribute__((always_inline)) fix16 fix16_div(fix16 a, fix16 b)
{
    if (__builtin_constant_p(b.v) && b.v != 0) {
        if ((b.v & 0xFFFF) == 0)
            return fix16::raw(a.v / (b.v >> 16));
        uint32_t m = (uint32_t)(b.v < 0 ? -b.v : b.v);
        uint32_t g = (m & (0u - m)) > 65536u ? 65536u : (m & (0u - m));   // gcd(2^16, m)
        int32_t num = (int32_t)(65536u / g), den = (int32_t)(m / g);
        if (b.v < 0) num = -num;
        if (num <= 256 && num >= -256)
            return fix16::raw(a.v * num / den);
    }
    if (b.v == 0)
        return fix16::raw(a.v < 0 ? INT32_MIN : INT32_MAX);
    return fix16::raw((int32_t)(((int64_t)a.v << 16) / b.v));
}

inline __attribute__((always_inline)) fix16 &fix16::operator*=(fix16 b) { *this = fix16_mul(*this, b); return *this; }
inline __attribute__((always_inline)) fix16 &fix16::operator/=(fix16 b) { *this = fix16_div(*this, b); return *this; }

static constexpr inline fix16 operator+(fix16 a, fix16 b) { return fix16::raw(a.v + b.v); }
static constexpr inline fix16 operator-(fix16 a, fix16 b) { return fix16::raw(a.v - b.v); }
static inline __attribute__((always_inline)) fix16 operator*(fix16 a, fix16 b) { return fix16_mul(a, b); }
static inline __attribute__((always_inline)) fix16 operator/(fix16 a, fix16 b) { return fix16_div(a, b); }
static constexpr inline bool operator<(fix16 a, fix16 b) { return a.v < b.v; }
static constexpr inline bool operator>(fix16 a, fix16 b) { return a.v > b.v; }
static constexpr inline bool operator<=(fix16 a, fix16 b) { return a.v <= b.v; }
static constexpr inline bool operator>=(fix16 a, fix16 b) { return a.v >= b.v; }
static constexpr inline bool operator==(fix16 a, fix16 b) { return a.v == b.v; }
static constexpr inline bool operator!=(fix16 a, fix16 b) { return a.v != b.v; }

// mixed fix16 / integer operands: exact-match templates beat the int conversions
#define FIX16_MIXED(OP, R)                                                              \
    template <class I, class = decltype(fix16((I)0)), class = typename fix16_int<I>::t> \
    static inline __attribute__((always_inline)) R operator OP(fix16 a, I b) { return a OP fix16(b); }                 \
    template <class I, class = decltype(fix16((I)0)), class = typename fix16_int<I>::t> \
    static inline __attribute__((always_inline)) R operator OP(I a, fix16 b) { return fix16(a) OP b; }
template <class I> struct fix16_int {};
#define FIX16_INT(T) template <> struct fix16_int<T> { typedef T t; };
FIX16_INT(int) FIX16_INT(unsigned) FIX16_INT(long) FIX16_INT(unsigned long)
FIX16_INT(short) FIX16_INT(unsigned short) FIX16_INT(signed char) FIX16_INT(unsigned char)
FIX16_INT(char) FIX16_INT(bool)
FIX16_MIXED(+, fix16) FIX16_MIXED(-, fix16) FIX16_MIXED(*, fix16) FIX16_MIXED(/, fix16)
FIX16_MIXED(<, bool) FIX16_MIXED(>, bool) FIX16_MIXED(<=, bool) FIX16_MIXED(>=, bool)
FIX16_MIXED(==, bool) FIX16_MIXED(!=, bool)

#define FIX16_RAW(r) (fix16::raw(r))

// ?: in macros (max/min/clamp/abs): both arms converted to the common type
template <class A, class B> struct fix16_ct { typedef decltype(true ? A() : B()) t; };
template <class B> struct fix16_ct<fix16, B> { typedef fix16 t; };
template <class A> struct fix16_ct<A, fix16> { typedef fix16 t; };
template <> struct fix16_ct<fix16, fix16> { typedef fix16 t; };
template <class T> struct fix16_rm { typedef T t; };
template <class T> struct fix16_rm<T &> { typedef T t; };
template <class T> struct fix16_rm<const T> { typedef T t; };
template <class T> struct fix16_rm<const T &> { typedef T t; };
template <class T> struct fix16_rm<volatile T> { typedef T t; };
template <class T> struct fix16_rm<volatile T &> { typedef T t; };
#define FIX16_TY(x) typename fix16_rm<decltype(x)>::t
#define FIX16_TERN(c, a, b) ((c) ? (typename fix16_ct<FIX16_TY(a), FIX16_TY(b)>::t)(a) \
                                 : (typename fix16_ct<FIX16_TY(a), FIX16_TY(b)>::t)(b))
#endif
