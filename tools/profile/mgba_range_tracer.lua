-- mgba_range_tracer.lua — best-effort mGBA (>= 0.10) scripting port of range_tracer.py.
--
-- STATUS: UNTESTED. mGBA scripting needs the Qt frontend (Tools > Scripting) and was not
-- available headless on the development machine. The authoritative tracer is
-- tools/profile/range_tracer.py (Unicorn).
--
-- What it does: sets a breakpoint on every PC listed in TRACE_PCS (normally generated
-- from the lifted IR: the instruction *after* each definition) and records the value of
-- the destination register, accumulating min/max/bitmask_or/stride in the same JSON
-- format documented in docs/profile_format.md ("regs" section only; memory watchpoints
-- are left as a TODO because watchpoint callbacks do not expose the written value).
--
-- Usage inside mGBA: load the ROM, then File > Load script. Edit TRACE_PCS / OUT_PATH.

local TRACE_PCS = {
  -- { pc = 0x08000004, def_pc = 0x08000002, reg = 3 },
}
local OUT_PATH = "range_profile_mgba.json"
local stats = {}

local function gcd(a, b)
  while b ~= 0 do a, b = b, a % b end
  return a
end

local function s32(v) if v >= 0x80000000 then return v - 0x100000000 end return v end

local function record(key, v)
  local st = stats[key]
  if st == nil then
    stats[key] = { count = 1, umin = v, umax = v, smin = s32(v), smax = s32(v),
                   bitmask_or = v, first = v, stride = 0 }
    return
  end
  st.count = st.count + 1
  if v < st.umin then st.umin = v end
  if v > st.umax then st.umax = v end
  local s = s32(v)
  if s < st.smin then st.smin = s end
  if s > st.smax then st.smax = s end
  st.bitmask_or = st.bitmask_or | v
  st.stride = gcd(st.stride, math.abs(v - st.first))
end

for _, t in ipairs(TRACE_PCS) do
  local key = string.format("0x%08x:r%d", t.def_pc, t.reg)
  emu:setBreakpoint(function()
    record(key, emu:readRegister("r" .. t.reg) & 0xFFFFFFFF)
  end, t.pc)
end

local function dump()
  local f = io.open(OUT_PATH, "w")
  f:write('{"format": "gba2gb-range-profile/1", "source": "mgba", "regs": {')
  local first = true
  for k, st in pairs(stats) do
    if not first then f:write(",") end
    first = false
    f:write(string.format('\n "%s": {"count": %d, "umin": %d, "umax": %d, "smin": %d, "smax": %d, "bitmask_or": %d, "stride": %d}',
      k, st.count, st.umin, st.umax, st.smin, st.smax, st.bitmask_or, st.stride))
  end
  f:write('\n}, "mem": {}}\n')
  f:close()
end

-- Dump the profile once per second of emulated time.
local frames = 0
callbacks:add("frame", function()
  frames = frames + 1
  if frames % 60 == 0 then dump() end
end)
console:log("mgba_range_tracer: " .. #TRACE_PCS .. " trace points")
