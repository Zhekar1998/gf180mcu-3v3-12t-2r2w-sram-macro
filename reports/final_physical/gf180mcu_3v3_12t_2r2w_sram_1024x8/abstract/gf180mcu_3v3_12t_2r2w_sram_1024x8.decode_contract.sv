// Synthesizable decode/control contract for gf180mcu_3v3_12t_2r2w_sram_1024x8.
// External MCU-facing address remains flat addr[9:0].
// Internal physical split is bank=addr[9:8], row=addr[7:0].
module gf180mcu_3v3_12t_2r2w_sram_1024x8_periphery_decode_contract #(
    parameter int ROWS = 1024,
    parameter int DATA_WIDTH = 8,
    parameter int BANKS = 4,
    parameter int ADDR_WIDTH = 10,
    parameter int BANK_ADDR_WIDTH = 2,
    parameter int ROW_ADDR_WIDTH = 8,
    parameter int ROWS_PER_BANK = 256
) (
    input  logic                         w0_en,
    input  logic                         w1_en,
    input  logic                         r0_en,
    input  logic                         r1_en,
    input  logic [ADDR_WIDTH-1:0]        w0_addr,
    input  logic [ADDR_WIDTH-1:0]        w1_addr,
    input  logic [ADDR_WIDTH-1:0]        r0_addr,
    input  logic [ADDR_WIDTH-1:0]        r1_addr,
    input  logic [DATA_WIDTH-1:0]        w0_data,
    input  logic [DATA_WIDTH-1:0]        w1_data,
    input  logic [DATA_WIDTH-1:0]        r0_sense_data,
    input  logic [DATA_WIDTH-1:0]        r1_sense_data,
    output logic                         w0_fire,
    output logic                         w1_fire,
    output logic                         write_conflict,
    output logic [BANK_ADDR_WIDTH-1:0]   w0_bank,
    output logic [BANK_ADDR_WIDTH-1:0]   w1_bank,
    output logic [BANK_ADDR_WIDTH-1:0]   r0_bank,
    output logic [BANK_ADDR_WIDTH-1:0]   r1_bank,
    output logic [ROW_ADDR_WIDTH-1:0]    w0_row,
    output logic [ROW_ADDR_WIDTH-1:0]    w1_row,
    output logic [ROW_ADDR_WIDTH-1:0]    r0_row,
    output logic [ROW_ADDR_WIDTH-1:0]    r1_row,
    output logic [BANKS-1:0]             w0_bank_oh,
    output logic [BANKS-1:0]             w1_bank_oh,
    output logic [BANKS-1:0]             r0_bank_oh,
    output logic [BANKS-1:0]             r1_bank_oh,
    output logic [ROWS_PER_BANK-1:0]     w0_row_oh,
    output logic [ROWS_PER_BANK-1:0]     w1_row_oh,
    output logic [ROWS_PER_BANK-1:0]     r0_row_oh,
    output logic [ROWS_PER_BANK-1:0]     r1_row_oh,
    output logic [ROWS-1:0]              w0_wordline_oh,
    output logic [ROWS-1:0]              w1_wordline_oh,
    output logic [ROWS-1:0]              r0_wordline_oh,
    output logic [ROWS-1:0]              r1_wordline_oh,
    output logic                         r0_bypass_hit,
    output logic                         r1_bypass_hit,
    output logic [DATA_WIDTH-1:0]        r0_data_muxed,
    output logic [DATA_WIDTH-1:0]        r1_data_muxed
);
    function automatic logic [BANKS-1:0] decode_bank(
        input logic en,
        input logic [BANK_ADDR_WIDTH-1:0] bank
    );
        decode_bank = '0;
        if (en) decode_bank[bank] = 1'b1;
    endfunction

    function automatic logic [ROWS_PER_BANK-1:0] decode_row(
        input logic en,
        input logic [ROW_ADDR_WIDTH-1:0] row
    );
        decode_row = '0;
        if (en) decode_row[row] = 1'b1;
    endfunction

    function automatic logic [ROWS-1:0] decode_wordline(
        input logic en,
        input logic [ADDR_WIDTH-1:0] addr
    );
        decode_wordline = '0;
        if (en) decode_wordline[addr] = 1'b1;
    endfunction

    assign w0_bank = w0_addr[ADDR_WIDTH-1:ROW_ADDR_WIDTH];
    assign w1_bank = w1_addr[ADDR_WIDTH-1:ROW_ADDR_WIDTH];
    assign r0_bank = r0_addr[ADDR_WIDTH-1:ROW_ADDR_WIDTH];
    assign r1_bank = r1_addr[ADDR_WIDTH-1:ROW_ADDR_WIDTH];
    assign w0_row = w0_addr[ROW_ADDR_WIDTH-1:0];
    assign w1_row = w1_addr[ROW_ADDR_WIDTH-1:0];
    assign r0_row = r0_addr[ROW_ADDR_WIDTH-1:0];
    assign r1_row = r1_addr[ROW_ADDR_WIDTH-1:0];

    assign write_conflict = w0_en && w1_en && (w0_addr == w1_addr);
    assign w0_fire = w0_en;
    assign w1_fire = w1_en && !write_conflict;

    assign w0_bank_oh = decode_bank(w0_fire, w0_bank);
    assign w1_bank_oh = decode_bank(w1_fire, w1_bank);
    assign r0_bank_oh = decode_bank(r0_en, r0_bank);
    assign r1_bank_oh = decode_bank(r1_en, r1_bank);
    assign w0_row_oh = decode_row(w0_fire, w0_row);
    assign w1_row_oh = decode_row(w1_fire, w1_row);
    assign r0_row_oh = decode_row(r0_en, r0_row);
    assign r1_row_oh = decode_row(r1_en, r1_row);
    assign w0_wordline_oh = decode_wordline(w0_fire, w0_addr);
    assign w1_wordline_oh = decode_wordline(w1_fire, w1_addr);
    assign r0_wordline_oh = decode_wordline(r0_en, r0_addr);
    assign r1_wordline_oh = decode_wordline(r1_en, r1_addr);

    always_comb begin
        r0_bypass_hit = 1'b0;
        r0_data_muxed = r0_sense_data;
        if (r0_en && w0_fire && (r0_addr == w0_addr)) begin
            r0_bypass_hit = 1'b1;
            r0_data_muxed = w0_data;
        end
        if (r0_en && w1_fire && (r0_addr == w1_addr)) begin
            r0_bypass_hit = 1'b1;
            r0_data_muxed = w1_data;
        end
    end

    always_comb begin
        r1_bypass_hit = 1'b0;
        r1_data_muxed = r1_sense_data;
        if (r1_en && w0_fire && (r1_addr == w0_addr)) begin
            r1_bypass_hit = 1'b1;
            r1_data_muxed = w0_data;
        end
        if (r1_en && w1_fire && (r1_addr == w1_addr)) begin
            r1_bypass_hit = 1'b1;
            r1_data_muxed = w1_data;
        end
    end
endmodule
