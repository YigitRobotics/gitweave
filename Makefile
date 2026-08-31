CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
SRC = src/fastscan.c
BIN = src/fastscan

.PHONY: all clean test

all: $(BIN)

$(BIN): $(SRC)
	$(CC) $(CFLAGS) -o $(BIN) $(SRC)

clean:
	rm -f $(BIN)

test: all
	python3 -m pytest -q tests/
