(* black_box *)
module gf180mcu_3v3_12t_2r2w_sram_1024x32 (
    input  logic                  clk,
    input  logic                  w0_en,
    input  logic                  w1_en,
    input  logic                  r0_en,
    input  logic                  r1_en,
    input  logic [9:0]           w0_addr,
    input  logic [9:0]           w1_addr,
    input  logic [9:0]           r0_addr,
    input  logic [9:0]           r1_addr,
    input  logic [31:0]          w0_data,
    input  logic [31:0]          w1_data,
    output logic [31:0]          r0_data,
    output logic [31:0]          r1_data,
    inout  wire                   VDD,
    inout  wire                   VSS
);
endmodule
