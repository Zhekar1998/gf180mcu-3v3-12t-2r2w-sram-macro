// Simulation-only SRAM model matching the intended MCU-facing 2W2R contract.
module gf180mcu_3v3_12t_2r2w_sram_1024x32_behavioral_model #(
    parameter int ROWS = 1024,
    parameter int DATA_WIDTH = 32,
    parameter int ADDR_WIDTH = 10
) (
    input  logic                  clk,
    input  logic                  w0_en,
    input  logic                  w1_en,
    input  logic                  r0_en,
    input  logic                  r1_en,
    input  logic [ADDR_WIDTH-1:0] w0_addr,
    input  logic [ADDR_WIDTH-1:0] w1_addr,
    input  logic [ADDR_WIDTH-1:0] r0_addr,
    input  logic [ADDR_WIDTH-1:0] r1_addr,
    input  logic [DATA_WIDTH-1:0] w0_data,
    input  logic [DATA_WIDTH-1:0] w1_data,
    output logic [DATA_WIDTH-1:0] r0_data,
    output logic [DATA_WIDTH-1:0] r1_data,
    output logic                  write_conflict
);
    logic [DATA_WIDTH-1:0] mem [0:ROWS-1];
    logic w0_fire;
    logic w1_fire;

    assign write_conflict = w0_en && w1_en && (w0_addr == w1_addr);
    assign w0_fire = w0_en;
    assign w1_fire = w1_en && !write_conflict;

    always_ff @(posedge clk) begin
        if (w0_fire) mem[w0_addr] <= w0_data;
        if (w1_fire) mem[w1_addr] <= w1_data;
    end

    always_comb begin
        r0_data = r0_en ? mem[r0_addr] : '0;
        if (r0_en && w0_fire && (r0_addr == w0_addr)) r0_data = w0_data;
        if (r0_en && w1_fire && (r0_addr == w1_addr)) r0_data = w1_data;
    end

    always_comb begin
        r1_data = r1_en ? mem[r1_addr] : '0;
        if (r1_en && w0_fire && (r1_addr == w0_addr)) r1_data = w0_data;
        if (r1_en && w1_fire && (r1_addr == w1_addr)) r1_data = w1_data;
    end
endmodule
