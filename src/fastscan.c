/*
 * fastscan.c
 *
 * Performance-critical file-system scanner for gitweave.
 * Recursively walks a directory tree and, for every regular file,
 * computes:
 *   - size in bytes
 *   - last modification time (st_mtime, seconds since epoch)
 *   - line count (number of '\n' bytes)
 *   - a fast FNV-1a 64-bit content hash
 *   - a binary/text heuristic (looks for a NUL byte in the first 8KB)
 *
 * Results are streamed to stdout as JSON Lines (one JSON object per file),
 * which the Python side parses. Doing this in C matters once repos get into
 * the tens of thousands of files / large binary assets range, where a pure
 * Python os.walk + open().read() loop is the bottleneck.
 *
 * Usage:
 *   fastscan <root_dir> [ignore_name ...]
 *
 * Ignored directory *names* (not paths) are skipped entirely, e.g.:
 *   fastscan . .git node_modules venv __pycache__ .idea .vscode dist build
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdint.h>

#define MAX_PATH_LEN 4096
#define READ_CHUNK 8192

static char **ignore_list = NULL;
static int ignore_count = 0;

static int is_ignored(const char *name) {
    for (int i = 0; i < ignore_count; i++) {
        if (strcmp(name, ignore_list[i]) == 0) return 1;
    }
    return 0;
}

/* FNV-1a 64-bit */
static uint64_t fnv1a_init(void) { return 1469598103934665603ULL; }
static uint64_t fnv1a_update(uint64_t h, const unsigned char *buf, size_t len) {
    for (size_t i = 0; i < len; i++) {
        h ^= buf[i];
        h *= 1099511628211ULL;
    }
    return h;
}

/* Escape a string for embedding in a JSON string literal. */
static void json_escape_print(FILE *out, const char *s) {
    fputc('"', out);
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        switch (*p) {
            case '"':  fputs("\\\"", out); break;
            case '\\': fputs("\\\\", out); break;
            case '\n': fputs("\\n", out); break;
            case '\r': fputs("\\r", out); break;
            case '\t': fputs("\\t", out); break;
            default:
                if (*p < 0x20) fprintf(out, "\\u%04x", *p);
                else fputc(*p, out);
        }
    }
    fputc('"', out);
}

static void scan_file(const char *path, FILE *out) {
    struct stat st;
    if (stat(path, &st) != 0) return;

    FILE *f = fopen(path, "rb");
    if (!f) return;

    unsigned char buf[READ_CHUNK];
    size_t n;
    long line_count = 0;
    uint64_t hash = fnv1a_init();
    int is_binary = 0;
    int checked_binary = 0;
    size_t total_read = 0;

    while ((n = fread(buf, 1, READ_CHUNK, f)) > 0) {
        hash = fnv1a_update(hash, buf, n);
        for (size_t i = 0; i < n; i++) {
            if (buf[i] == '\n') line_count++;
        }
        if (!checked_binary) {
            size_t look = n < 8192 ? n : 8192;
            for (size_t i = 0; i < look; i++) {
                if (buf[i] == 0) { is_binary = 1; break; }
            }
            checked_binary = 1;
        }
        total_read += n;
    }
    fclose(f);

    fputc('{', out);
    fputs("\"path\":", out);
    json_escape_print(out, path);
    fprintf(out,
        ",\"size\":%lld,\"mtime\":%lld,\"lines\":%ld,\"hash\":\"%016llx\",\"binary\":%s}\n",
        (long long)st.st_size,
        (long long)st.st_mtime,
        line_count,
        (unsigned long long)hash,
        is_binary ? "true" : "false");
}

static void walk(const char *dir, FILE *out) {
    DIR *d = opendir(dir);
    if (!d) return;

    struct dirent *entry;
    char path[MAX_PATH_LEN];

    while ((entry = readdir(d)) != NULL) {
        const char *name = entry->d_name;
        if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) continue;
        if (is_ignored(name)) continue;

        int written = snprintf(path, sizeof(path), "%s/%s", dir, name);
        if (written < 0 || (size_t)written >= sizeof(path)) continue;

        struct stat st;
        if (lstat(path, &st) != 0) continue;

        if (S_ISDIR(st.st_mode)) {
            walk(path, out);
        } else if (S_ISREG(st.st_mode)) {
            scan_file(path, out);
        }
        /* symlinks intentionally skipped to avoid cycles */
    }
    closedir(d);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <root_dir> [ignore_name ...]\n", argv[0]);
        return 1;
    }

    ignore_count = argc - 2;
    if (ignore_count > 0) {
        ignore_list = &argv[2];
    }

    walk(argv[1], stdout);
    return 0;
}
