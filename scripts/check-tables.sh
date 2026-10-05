#!/bin/sh
# Compare the register tables of two Qualcomm clock or pinctrl drivers.
#
# Mainlining SM6450 means transcribing Qualcomm's downstream parrot drivers
# into mainline idiom (see docs/06-mainline.md). The idiom changes; the
# register offsets must not. This checks that mechanically, so a 3000-line
# transcription can be trusted without booting anything.
#
# The method is the one that identified SM4450 as parrot's sibling: extract
# every (symbol, register offset) pair from both files and join them. The
# known-good self-test is the ravelin/sm4450 pair, which must come out at
# 119 common clocks and 119 identical offsets:
#
#   scripts/check-tables.sh clk gcc-ravelin.c gcc-sm4450.c
#
# Real use compares a written mainline driver against the vendor source it
# came from:
#
#   scripts/check-tables.sh clk     gcc-parrot.c      gcc-sm6450.c
#   scripts/check-tables.sh pinctrl pinctrl-parrot.h  pinctrl-sm6450.c
#
# Exits nonzero if any shared symbol disagrees on its offset.
set -eu

MODE=${1:-}
REF=${2:-}
CAND=${3:-}

usage() {
	echo "usage: $0 <clk|pinctrl> <reference-file> <candidate-file>" >&2
	echo "  reference: the vendor/downstream driver, treated as ground truth" >&2
	echo "  candidate: the mainline driver being checked against it" >&2
	exit 2
}

[ -n "$MODE" ] && [ -n "$REF" ] && [ -n "$CAND" ] || usage
case "$MODE" in clk|pinctrl) ;; *) usage ;; esac
for f in "$REF" "$CAND"; do
	[ -f "$f" ] || { echo "error: no such file: $f" >&2; exit 2; }
done

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Qualcomm clock drivers put the offset before the name, in either a
# clk_branch (.halt_reg) or an rcg (.cmd_rcgr), with the .name several lines
# down inside the nested clkr/hw.init initialiser. Walk the file keeping the
# most recent offset and emit it when the name shows up.
extract_clk() {
	awk '
		/\.(halt_reg|cmd_rcgr)[[:space:]]*=[[:space:]]*0x/ {
			match($0, /0x[0-9a-fA-F]+/)
			off = tolower(substr($0, RSTART, RLENGTH))
		}
		/\.name[[:space:]]*=[[:space:]]*"/ {
			if (off != "") {
				match($0, /"[^"]+"/)
				print substr($0, RSTART + 1, RLENGTH - 2) "\t" off
				off = ""
			}
		}
	' "$1" | sort -u
}

# Pinctrl tables are PINGROUP(id, f1..f9, ...) invocations giving each pin its
# mux functions. Two wrinkles: an invocation wraps over several lines, and
# downstream carries two extra trailing arguments (wake_off, bit) that mainline
# drops. So collapse each invocation onto one line by tracking paren depth,
# then compare only id and f1..f9 - the mux assignment, which must be
# identical. Downstream keeps these in a .h and mainline in the .c; both read
# the same way.
extract_pinctrl() {
	awk '
		function parens(s,   o, c, t) {
			t = s; o = gsub(/\(/, "(", t)
			t = s; c = gsub(/\)/, ")", t)
			return o - c
		}
		function emit(s,   n, a, i, out) {
			sub(/^[^(]*\(/, "", s)
			sub(/\)[^)]*$/, "", s)
			n = split(s, a, ",")
			if (n < 10) return
			out = ""
			for (i = 2; i <= 10; i++) {
				gsub(/^[[:space:]]+|[[:space:]]+$/, "", a[i])
				out = out (i > 2 ? "," : "") a[i]
			}
			gsub(/^[[:space:]]+|[[:space:]]+$/, "", a[1])
			print "pin" a[1] "\t" out
		}
		{
			l = $0
			gsub(/\/\*[^*]*\*\//, "", l)   # inline comments
			sub(/\\[[:space:]]*$/, "", l)  # macro line continuations
		}
		depth > 0 {
			cur = cur " " l
			depth += parens(l)
			if (depth <= 0) { emit(cur); cur = ""; depth = 0 }
			next
		}
		/(^|[^A-Za-z0-9_])PINGROUP\([0-9]+,/ {
			match(l, /(^|[^A-Za-z0-9_])PINGROUP\([0-9]+,/)
			cur = substr(l, RSTART)
			depth = parens(cur)
			if (depth <= 0) { emit(cur); cur = ""; depth = 0 }
		}
	' "$1" | sort -u
}

case "$MODE" in
clk)     extract_clk     "$REF"  > "$WORK/ref"; extract_clk     "$CAND" > "$WORK/cand" ;;
pinctrl) extract_pinctrl "$REF"  > "$WORK/ref"; extract_pinctrl "$CAND" > "$WORK/cand" ;;
esac

nref=$(wc -l < "$WORK/ref")
ncand=$(wc -l < "$WORK/cand")

echo "==> $MODE table comparison"
printf '    reference %-28s %s entries\n' "$(basename "$REF")"  "$nref"
printf '    candidate %-28s %s entries\n' "$(basename "$CAND")" "$ncand"

if [ "$nref" -eq 0 ] || [ "$ncand" -eq 0 ]; then
	echo "    ERROR: extracted nothing from one side - wrong mode for these files?" >&2
	exit 2
fi

join -t"$(printf '\t')" "$WORK/ref" "$WORK/cand" > "$WORK/both"

# Clock offsets must match exactly - they are hardware addresses.
#
# Pinctrl mux names cannot be compared that way. Mainline deliberately
# collapses downstream's per-signal names into one function group per mux slot
# (downstream qup1_se0_l0 / cmu_rng_entropy3 / phase_flag_status27 become
# mainline qup1_se0 / cmu_rng / phase_flag) and spells "unused" as _ rather
# than NA. An exact comparison is therefore 100% false positives. What still
# has to hold, slot by slot, is that both sides agree a slot is unused, or the
# mainline name is a prefix of the vendor one. That catches the errors that
# matter - a function in the wrong slot, a shifted or dropped pin - while
# accepting the rename convention.
case "$MODE" in
clk)
	awk -F'\t' '$2 != $3' "$WORK/both" > "$WORK/bad"
	;;
pinctrl)
	awk -F'\t' '
		function norm(s) { return (s == "NA" || s == "na") ? "_" : s }
		{
			nr = split($2, r, ","); nc = split($3, c, ",")
			bad = (nr != nc)
			for (i = 1; i <= nr && !bad; i++) {
				a = norm(r[i]); b = norm(c[i])
				if (a == "_" && b == "_") continue
				if (b == "_" || a == "_") { bad = 1; break }
				if (index(a, b) != 1) bad = 1
			}
			if (bad) print
		}
	' "$WORK/both" > "$WORK/bad"
	;;
esac
comm -23 "$WORK/ref"  "$WORK/cand" | cut -f1 | sort -u > "$WORK/ref_only_raw"
comm -13 "$WORK/ref"  "$WORK/cand" | cut -f1 | sort -u > "$WORK/cand_only_raw"
cut -f1 "$WORK/both" | sort -u > "$WORK/common"
comm -23 "$WORK/ref_only_raw"  "$WORK/common" > "$WORK/ref_only"
comm -23 "$WORK/cand_only_raw" "$WORK/common" > "$WORK/cand_only"

ncommon=$(wc -l < "$WORK/common")
nbad=$(wc -l < "$WORK/bad")
printf '    common    %-28s %s entries\n' "" "$ncommon"

fail=0

echo
if [ "$nbad" -eq 0 ]; then
	printf '    OK: all %s shared entries agree\n' "$ncommon"
else
	printf '    MISMATCH on %s shared entries:\n' "$nbad"
	awk -F'\t' '{printf "      %-44s ref:%-12s cand:%s\n", $1, $2, $3}' "$WORK/bad"
	fail=1
fi

# Entries only in the reference are the ones to look at: something in the
# vendor driver did not make it across. The reverse is usually fine, since
# mainline names some clocks the vendor tree does not expose.
if [ -s "$WORK/ref_only" ]; then
	echo
	printf '    in reference only (%s) - dropped, or renamed on purpose:\n' "$(wc -l < "$WORK/ref_only")"
	sed 's/^/      /' "$WORK/ref_only" | head -25
	[ "$(wc -l < "$WORK/ref_only")" -gt 25 ] && echo "      ... and more"
fi

if [ -s "$WORK/cand_only" ]; then
	echo
	printf '    in candidate only (%s):\n' "$(wc -l < "$WORK/cand_only")"
	sed 's/^/      /' "$WORK/cand_only" | head -25
	[ "$(wc -l < "$WORK/cand_only")" -gt 25 ] && echo "      ... and more"
fi

echo
if [ "$fail" -eq 0 ]; then
	echo "==> pass"
else
	case "$MODE" in
	clk)     echo "==> FAIL: register offsets disagree, do not boot this" ;;
	pinctrl) echo "==> FAIL: mux assignment disagrees, do not boot this" ;;
	esac
fi
exit "$fail"
