// Minimal DIMACS solver harness: feed a CNF to ABC's vendored Kissat or
// CaDiCaL, optionally with a phase-hint sidecar, time the solve.
//
// Usage:
//   sat_bench --kissat|--cadical [--phase file.phase] [--dump-model file.phase] input.cnf
// Output (one line):
//   <SAT|UNSAT|UNKNOWN> wall_s=<seconds>
// Exit code: 10 SAT, 20 UNSAT, 0 unknown / error printed to stderr.
//
// --dump-model writes the satisfying assignment in DIMACS phase-hint
// form ("+var" or "-var" per line) — suitable for feeding as --phase
// on a subsequent run.

#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>

// CaDiCaL C++ header is in the ABC tree under src/sat/cadical/.
#include "cadical.hpp"

// Kissat is C with a `kissat` opaque struct.
extern "C" {
    struct kissat;
    kissat *kissat_init(void);
    void kissat_add(kissat *, int);
    int kissat_solve(kissat *);
    int kissat_value(kissat *, int lit);
    void kissat_release(kissat *);
    void kissat_reserve(kissat *, int);
    int kissat_set_option(kissat *, const char *name, int new_value);
}

static int parse_dimacs_kissat(FILE *f, kissat *s, int *out_nvars) {
    int nvars = 0, lit = 0, ch;
    bool in_clause = false;
    bool in_header = false;
    bool in_comment = false;
    auto skipline = [&]() {
        while ((ch = fgetc(f)) != EOF && ch != '\n');
    };
    while ((ch = fgetc(f)) != EOF) {
        if (ch == 'c') { skipline(); continue; }
        if (ch == 'p') {
            // header: "p cnf <nvars> <nclauses>"
            int nv = 0, nc = 0;
            if (fscanf(f, " cnf %d %d", &nv, &nc) != 2) {
                fprintf(stderr, "sat_bench: bad header\n");
                return -1;
            }
            nvars = nv;
            kissat_reserve(s, nv);
            skipline();
            continue;
        }
        if (isspace(ch)) continue;
        if (ch == '-' || isdigit(ch)) {
            ungetc(ch, f);
            if (fscanf(f, "%d", &lit) != 1) {
                fprintf(stderr, "sat_bench: bad literal\n");
                return -1;
            }
            kissat_add(s, lit);
        }
    }
    *out_nvars = nvars;
    return 0;
}

static int load_phase_into_cadical(const char *path, CaDiCaL::Solver &s) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "sat_bench: cannot open phase file %s\n", path); return -1; }
    int lit;
    int n = 0;
    while (fscanf(f, "%d", &lit) == 1) {
        if (lit == 0) continue;
        s.phase(lit);
        n++;
    }
    fclose(f);
    fprintf(stderr, "sat_bench: applied %d phase hints from %s\n", n, path);
    return 0;
}

int main(int argc, char **argv) {
    bool use_kissat = false;
    bool engine_set = false;
    const char *phase_file = nullptr;
    const char *cnf_file = nullptr;
    const char *cad_opt = nullptr;
    const char *kis_opt = nullptr;
    const char *dump_model = nullptr;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--kissat"))       { use_kissat = true;  engine_set = true; }
        else if (!strcmp(argv[i], "--cadical")) { use_kissat = false; engine_set = true; }
        else if (!strcmp(argv[i], "--phase") && i + 1 < argc) { phase_file = argv[++i]; }
        else if (!strcmp(argv[i], "--cad-opt") && i + 1 < argc) { cad_opt = argv[++i]; }
        else if (!strcmp(argv[i], "--kis-opt") && i + 1 < argc) { kis_opt = argv[++i]; }
        else if (!strcmp(argv[i], "--dump-model") && i + 1 < argc) { dump_model = argv[++i]; }
        else if (argv[i][0] != '-')             { cnf_file = argv[i]; }
        else {
            fprintf(stderr, "sat_bench: unknown arg %s\n", argv[i]);
            return 1;
        }
    }
    if (!engine_set || !cnf_file) {
        fprintf(stderr, "usage: sat_bench --kissat|--cadical [--phase file.phase] input.cnf\n");
        return 1;
    }
    if (use_kissat && phase_file) {
        fprintf(stderr, "sat_bench: --phase is not supported with --kissat (kissat has no per-var phase API)\n");
        return 1;
    }

    int status = 0;
    int total_vars = 0;
    auto t0 = std::chrono::steady_clock::now();

    if (use_kissat) {
        FILE *f = fopen(cnf_file, "r");
        if (!f) { fprintf(stderr, "sat_bench: cannot open %s\n", cnf_file); return 1; }
        kissat *s = kissat_init();
        if (kis_opt) {
            char buf[1024];
            strncpy(buf, kis_opt, sizeof(buf)-1); buf[sizeof(buf)-1] = 0;
            char *tok = strtok(buf, ",");
            while (tok) {
                char *eq = strchr(tok, '=');
                if (eq) {
                    *eq = 0;
                    int v = atoi(eq + 1);
                    if (!kissat_set_option(s, tok, v))
                        fprintf(stderr, "sat_bench: kissat rejected option %s=%d\n", tok, v);
                }
                tok = strtok(nullptr, ",");
            }
        }
        int nvars = 0;
        if (parse_dimacs_kissat(f, s, &nvars) != 0) { fclose(f); return 1; }
        fclose(f);
        total_vars = nvars;
        status = kissat_solve(s);
        if (status == 10 && dump_model) {
            FILE *out = fopen(dump_model, "w");
            if (!out) { fprintf(stderr, "sat_bench: cannot open %s for model dump\n", dump_model); }
            else {
                for (int v = 1; v <= nvars; v++) {
                    int val = kissat_value(s, v);
                    if (val > 0) fprintf(out, "%d\n",  v);
                    else if (val < 0) fprintf(out, "%d\n", -v);
                    // val == 0 = don't care; skip
                }
                fclose(out);
            }
        }
        kissat_release(s);
    } else {
        CaDiCaL::Solver s;
        if (cad_opt) {
            // format: "name=value[,name=value]..."
            char buf[1024];
            strncpy(buf, cad_opt, sizeof(buf)-1); buf[sizeof(buf)-1] = 0;
            char *tok = strtok(buf, ",");
            while (tok) {
                char *eq = strchr(tok, '=');
                if (eq) {
                    *eq = 0;
                    int v = atoi(eq + 1);
                    if (!s.set(tok, v))
                        fprintf(stderr, "sat_bench: cadical rejected option %s=%d\n", tok, v);
                }
                tok = strtok(nullptr, ",");
            }
        }
        int vars = 0;
        const char *err = s.read_dimacs(cnf_file, vars, 1);
        if (err) { fprintf(stderr, "sat_bench: read_dimacs: %s\n", err); return 1; }
        total_vars = vars;
        if (phase_file) {
            if (load_phase_into_cadical(phase_file, s) != 0) return 1;
        }
        status = s.solve();
        if (status == 10 && dump_model) {
            FILE *out = fopen(dump_model, "w");
            if (!out) { fprintf(stderr, "sat_bench: cannot open %s for model dump\n", dump_model); }
            else {
                for (int v = 1; v <= vars; v++) {
                    int val = s.val(v);
                    if (val > 0) fprintf(out, "%d\n",  v);
                    else if (val < 0) fprintf(out, "%d\n", -v);
                }
                fclose(out);
            }
        }
    }

    auto t1 = std::chrono::steady_clock::now();
    double secs = std::chrono::duration<double>(t1 - t0).count();

    const char *st = (status == 10) ? "SAT" : (status == 20) ? "UNSAT" : "UNKNOWN";
    printf("%s wall_s=%.4f\n", st, secs);
    return (status == 10) ? 10 : (status == 20) ? 20 : 0;
}
