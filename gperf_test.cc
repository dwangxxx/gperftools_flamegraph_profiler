#include <iostream>

constexpr uint64_t kLoopCount = 10000000000;

void FuncA() {
  uint64_t add_num = 0;
  for (int i = 0; i < kLoopCount; ++i) {
    add_num += 1;
  }
}

void FuncB() {
  uint64_t res = 0;
  for (int i = 0; i < kLoopCount; ++i) {
    if (i % 2 == 0) {
      res += 2;
    } else {
      res -= 1;
    }
  }
}

int main() {
  FuncA();
  FuncB();

  return 0;
}
