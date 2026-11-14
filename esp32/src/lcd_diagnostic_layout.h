#pragma once
namespace LcdDiagnosticLayout {
constexpr bool valid(int pixels) { return pixels==16 || pixels==20 || pixels==24 || pixels==28 || pixels==32; }
constexpr int cellWidth(int pixels) { return pixels/2; }
constexpr int cellHeight(int pixels) { return pixels; }
constexpr int sourceRow(int y,int pixels) { return y*16/pixels; }
constexpr int sourceColumn(int x,int pixels) { return x*16/pixels; }
constexpr int columns(int pixels) { return 240/cellWidth(pixels); }
constexpr int capacity(int pixels) { return 135/pixels; }
constexpr int pageCount(int lines,int pixels) { return (lines+capacity(pixels)-1)/capacity(pixels); }
constexpr int centeredY(int visible,int pixels) { return (135-visible*pixels)/2; }
static_assert(capacity(16)==8 && capacity(20)==6 && capacity(24)==5 && capacity(28)==4 && capacity(32)==4,"page capacity");
static_assert(pageCount(6,32)==2 && pageCount(6,24)==2 && pageCount(6,20)==1,"overflow pages");
static_assert(centeredY(1,24)==55 && centeredY(2,24)==43 && centeredY(3,24)==31,"centered selections");
constexpr int top(int pixels) { return pixels==16?87:39; }
constexpr int rows(int) { return 3; }
constexpr bool fits(int pixels,int characters) { return characters*cellWidth(pixels)<=240; }
static_assert(cellWidth(16)==8 && cellHeight(16)==16,"16px");
static_assert(cellWidth(20)==10 && cellHeight(20)==20,"20px");
static_assert(cellWidth(24)==12 && cellHeight(24)==24,"24px");
static_assert(cellWidth(28)==14 && cellHeight(28)==28,"28px");
static_assert(cellWidth(32)==16 && cellHeight(32)==32,"32px");
static_assert(sourceRow(19,20)==15 && sourceColumn(9,20)==7,"20px resampling");
static_assert(sourceRow(23,24)==15 && sourceColumn(11,24)==7,"24px resampling");
static_assert(sourceRow(27,28)==15 && sourceColumn(13,28)==7,"28px resampling");
static_assert(top(16)+3*16==135 && top(32)+3*32==135,"existing layout");
static_assert(top(20)+3*20<=135 && top(24)+3*24<=135 && top(28)+3*28<=135,"new sizes fit");
static_assert(!valid(40) && !valid(48),"no oversized diagnostics");
}
