; KEYHOOK.ASM - 测试专用 INT 16H 拦截 + EXEC 加载器（无头验收提交版）
; 用途：无头运行提交版 HWSCOPE.EXE 的交互主循环（等键/ESC/重测），
;       补齐"提交版只构建不执行"的覆盖缺口（2026-10-23 审核发现）。
; 背景（实测结论，勿再试）：
;   1. INT 16H 不读重定向 stdin（KEYTEST 探针永久阻塞）；
;   2. INT 16H 不认手工 poke 的 BIOS 键盘缓冲 0040:001A/001C/001E
;      （探针返回垃圾键 20CD 后阻塞）；
;   3. 正解 = 钩住 INT 16H 向量：钩子从内置队列应答 AH=00 取键 / AH=01
;      窥键，队列空才链回原处理程序；装钩后 INT 21H/4Bh EXEC 目标程序。
; 注入键表 KEYTAB（字：高字节=扫描码，低字节=ASCII）：
;   2E58H='X'（非 ESC -> 触发重测一轮）  011BH=ESC（退出）
; 断言约定（主机侧）：hws.log 应恰含两行 "MEASURING..."（首轮+重测轮），
;   且 BAT 续写 SMOKE-DONE 标记；DISK.BIN 应已被子程序自删。
; ⚠️ PROG 为绝对 DOS 路径，依赖 gen_conf 的扁平运行根（D: = 运行根）。
STACK_BYTES EQU 512

CODE    SEGMENT
        ASSUME CS:CODE, DS:CODE

PSP_SEG DW 0                 ; 入口 PSP 段（4Ah 缩小内存用）
EXEC_SS DW 0                 ; EXEC 前保存父进程栈，返回后先恢复再压栈
EXEC_SP DW 0
OLD16   DD 0                 ; 原 INT 16H 向量（偏移:段）
KQ      DW 8 DUP(0)          ; 注入键队列（队首 KQ[0]）
KQN     DB 0                 ; 队列待取键数
KEYTAB  DW 2E58H             ; 'X'（非 ESC -> 重测一轮）
        DW 011BH             ; ESC（退出）
PROG    DB 'D:\src\HWSCOPE.EXE', 0
CMDTOK  DB 0, 0DH            ; 空命令尾（count=0 + CR）
FCB1    DB 16 DUP(0)         ; 伪 FCB（HWSCOPE 不用 FCB，占位）
FCB2    DB 16 DUP(0)
PARMBLK DW 0                 ; +0  环境段（0=继承）
        DW 0                 ; +2  命令尾段（运行时填 CS）
        DW 0                 ; +4  命令尾偏移
        DW 0                 ; +6  FCB1 段
        DW 0                 ; +8  FCB1 偏移
        DW 0                 ; +10 FCB2 段
        DW 0                 ; +12 FCB2 偏移

START:
        PUSH DS               ; PSP 段入栈
        PUSH CS
        POP DS                ; DS = CS（全部数据同段访问）
        POP PSP_SEG           ; PSP 段 -> CS:PSP_SEG
        ; STACK 是最后一个段；保留 PSP 到栈顶的全部段落，不能截掉栈
        MOV BX, SS
        SUB BX, PSP_SEG
        ADD BX, (STACK_BYTES+15)/16
        ; ---- 缩小内存块为 EXEC 腾空间（失败可忽略）----
        MOV AH, 4AH
        MOV ES, PSP_SEG
        INT 21H
        ; ---- 保存并钩住 INT 16H ----
        MOV AX, 3516H
        INT 21H               ; ES:BX = 原向量
        MOV WORD PTR OLD16, BX
        MOV WORD PTR OLD16+2, ES
        MOV DX, OFFSET HOOK16
        MOV AX, 2516H         ; DS:DX = CS:HOOK16
        INT 21H
        ; ---- 初始化注入队列 ----
        ; ⚠️ ES 必须先设为 CS：上面的 35h 调用把 ES 留在了原 INT 16H
        ;    向量的段（BIOS 段），REP MOVSB/MOVSW 用 ES:DI——不切段会把
        ;    键写进 BIOS 数据区（实测症状：KQN 正常递减但取键恒 0000）
        PUSH CS
        POP ES
        MOV CX, 2
        MOV KQN, CL
        CLD
        MOV SI, OFFSET KEYTAB
        MOV DI, OFFSET KQ
        REP MOVSW
        ; ---- 填 EXEC 参数块（ES:BX = CS:PARMBLK）----
        PUSH CS
        POP ES
        MOV AX, CS
        MOV PARMBLK+2, AX
        MOV PARMBLK+4, OFFSET CMDTOK
        MOV PARMBLK+6, AX
        MOV PARMBLK+8, OFFSET FCB1
        MOV PARMBLK+10, AX
        MOV PARMBLK+12, OFFSET FCB2
        ; ---- EXEC 子程序（DS:DX = CS:PROG）----
        MOV DX, OFFSET PROG
        MOV BX, OFFSET PARMBLK
        MOV EXEC_SS, SS
        MOV EXEC_SP, SP
        MOV AX, 4B00H
        INT 21H               ; CF=1 失败（AX=错误码）
        MOV SS, CS:EXEC_SS     ; MOV SS 后紧接 MOV SP，恢复期间不接受中断
        MOV SP, CS:EXEC_SP
        PUSH CS
        POP DS                ; EXEC 后不依赖返回的 DS
        PUSHF                 ; 保存 EXEC 的 CF 和 AX，成功/失败均先卸钩
        PUSH AX
        ; ---- 恢复 INT 16H 向量（DS:DX = 原向量）----
        MOV DX, WORD PTR OLD16
        MOV AX, WORD PTR OLD16+2
        MOV DS, AX
        MOV AX, 2516H
        INT 21H
        PUSH CS
        POP DS
        POP AX
        POPF
        JC  EXEC_FAIL
        ; ---- 透传子进程退出码 ----
        MOV AH, 4DH
        INT 21H
        MOV AH, 4CH
        INT 21H
EXEC_FAIL:
        MOV BX, AX            ; 打印 'E' + 错误码两位十六进制
        MOV DL, 'E'
        MOV AH, 02H
        INT 21H
        MOV AL, BH
        CALL PHEX
        MOV AL, BL
        CALL PHEX
        MOV DL, 0DH
        MOV AH, 02H
        INT 21H
        MOV DL, 0AH
        MOV AH, 02H
        INT 21H
        MOV AX, 4CFFH
        INT 21H

; ============================================================
; ---- INT 16H 钩子：AH=00 取键 / AH=01 窥键；空则链回原处理 ----
; 入口 DS 是调用方的段——查队列必须用 CS 段覆盖（曾因读调用方 DS 的
; 同偏移变量 RES_DSK_LO 而行为诡异）
; ============================================================
HOOK16:
        CMP AH, 01H
        JE  HK_PEEK
        CMP AH, 00H
        JNE HK_CHAIN
HK_READ:
        CMP CS:KQN, 0
        JE  HK_CHAIN
        PUSH SI
        PUSH DS
        PUSH CS
        POP DS                ; DS = CS 访问队列
        MOV SI, OFFSET KQ
        MOV AX, [SI]          ; 队首键
        MOV CX, 7             ; 队列前移
HK_SH:
        MOV DX, [SI+2]
        MOV [SI], DX
        ADD SI, 2
        LOOP HK_SH
        DEC KQN
        POP DS
        POP SI
        IRET
HK_PEEK:
        CMP CS:KQN, 0
        JE  HK_CHAIN
        PUSH DS
        PUSH CS
        POP DS
        MOV AX, KQ            ; 队首键（不取出）
        POP DS
        PUSH BP               ; 改 INT 帧栈上 Flags 的 ZF（bit6）：
        MOV BP, SP            ; IRET 恢复的是帧上标志，POPF 设置的
        AND WORD PTR [BP+6], 0FFBFH   ; 标志会被丢弃（实测：演示永不被跳过）
        POP BP
        IRET
HK_CHAIN:
        JMP CS:[OLD16]        ; 远跳回原 INT 16H

; ---- 打印 AL 两位十六进制 ----
PHEX    PROC
        PUSH AX
        PUSH CX
        PUSH DX
        MOV CL, 4
        MOV AH, AL
        SHR AL, CL            ; 8086：移位计数须 CL
        ADD AL, '0'
        CMP AL, '9'
        JBE PH1
        ADD AL, 7
PH1:    MOV DL, AL
        PUSH AX
        MOV AH, 02H
        INT 21H
        POP AX
        MOV AL, AH
        AND AL, 0FH
        ADD AL, '0'
        CMP AL, '9'
        JBE PH2
        ADD AL, 7
PH2:    MOV DL, AL
        MOV AH, 02H
        INT 21H
        POP DX
        POP CX
        POP AX
        RET
PHEX    ENDP
CODE    ENDS

; 必须放在 CODE 后：SS + 栈长即整个父进程需要保留的最高地址
STACK   SEGMENT PARA STACK 'STACK'
        DB STACK_BYTES DUP (?)
STACK   ENDS
        END START
