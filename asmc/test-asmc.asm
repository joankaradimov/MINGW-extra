; Encodings that asmc 2.39.17 got wrong. Like asmc's own x64-bin tests,
; this is assembled once as instructions and once, with -DBIN, as the
; bytes GNU as produces for them; the two outputs must match.

testcase macro B, S
 ifdef BIN
  db B
 else
  S
 endif
 endm

.code

; 0001: EVEX disp8*N applies to [reg+disp] only
testcase <0x62, 0xf1, 0x7c, 0x48, 0x10, 0x60, 0x04>, <vmovups zmm4, zmmword ptr [rax+256]>
ifdef BIN
  db 0x62, 0xf1, 0x7c, 0x48, 0x10, 0x25
  dd tbl+256-next1
next1:
  db 0x62, 0xf1, 0xed, 0x58, 0x58, 0x0d
  dd tbl+8-next2
next2:
  db 0x62, 0xf3, 0xbd, 0x40, 0x25, 0x05
  dd tbl+448-next3
  db 236
next3:
else
  vmovups zmm4, zmmword ptr [tbl+256]
  vaddpd zmm1, zmm2, qword bcst [tbl+8]
  vpternlogq zmm0, zmm24, zmmword ptr [tbl+448], 236
endif

; 0002: REX.R in the two-byte VEX prefix
testcase <0xc5, 0x61, 0x58, 0xc5>, <vaddpd xmm8, xmm3, xmm5>
testcase <0xc5, 0x63, 0x58, 0xc5>, <vaddsd xmm8, xmm3, xmm5>
testcase <0xc5, 0x79, 0x51, 0xc1>, <vsqrtpd xmm8, xmm1>

; 0003: the store-form swap, needed for REX.B alone
testcase <0xc4, 0x41, 0x79, 0x6f, 0xc2>, <vmovdqa xmm8, xmm10>
testcase <0xc5, 0x79, 0x7f, 0xc1>, <vmovdqa xmm1, xmm8>

tbl label byte
end
