#!/bin/sh
# Export the work-in-progress kernel branches out of out/linux.
#
# sync-kernel-patches.sh exports the sm6450 branch, the series. Everything
# not yet folded into it - the WIP device tree nodes each round tests, and
# the backports they lean on - lives on topic branches in out/linux, which
# git ignores. This writes each topic branch's own commits into
# kernel/wip/<branch>/, one patch per commit, so a lost or recloned tree
# loses nothing. "Own" is what `git cherry sm6450 <branch>` marks new:
# commits already on sm6450 under any SHA are left out. A branch stacked on
# another carries its parent's commits too, so every directory applies by
# itself onto the base its BASE file names.
#
#   scripts/export-wip.sh
#
# The -rNN and pre-* branches are snapshots of the series as an older
# pkgrel built it, and the aport's history already holds those; they are
# skipped.
#
# sm6450-fold, when it exists, is the series with WIP that has passed on
# the device folded into it, waiting for the next pkgrel to move sm6450
# there. It rewrites series commits, so it is exported whole, from the
# kernel release up, as a replacement for kernel/patches; and a branch cut
# from it is exported against it rather than against sm6450.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TREE=$ROOT/out/linux
OUT=$ROOT/kernel/wip
FOLD=sm6450-fold

[ -d "$TREE/.git" ] || { echo "no kernel tree at $TREE" >&2; exit 1; }

mkdir -p "$OUT"
for ref in $(git -C "$TREE" for-each-ref --format='%(refname:short)' 'refs/heads/sm6450-*'); do
	case "$ref" in
	*-r[0-9]* | sm6450-pre-*) continue ;;
	esac
	dest=$OUT/$ref
	mkdir -p "$dest"
	find "$dest" -maxdepth 1 -name '*.patch' -delete
	series=sm6450
	if [ "$ref" != "$FOLD" ] && git -C "$TREE" rev-parse -q --verify "refs/heads/$FOLD" >/dev/null &&
		git -C "$TREE" merge-base --is-ancestor "$FOLD" "$ref"; then
		series=$FOLD
	fi
	if [ "$ref" = "$FOLD" ]; then
		base=$(git -C "$TREE" merge-base origin/linux-6.18.y "$ref")
		commits=$(git -C "$TREE" rev-list --reverse "$base..$ref")
	else
		base=$(git -C "$TREE" merge-base "$series" "$ref")
		commits=$(git -C "$TREE" cherry "$series" "$ref" | sed -n 's/^+ //p')
	fi
	n=0
	for c in $commits; do
		n=$((n + 1))
		git -C "$TREE" format-patch -q --no-signature --zero-commit \
			--no-numbered --start-number "$n" -o "$dest" -1 "$c" >/dev/null
	done
	under=$(( $(git -C "$TREE" rev-list --count "$base..$ref") - n ))
	{
		echo "branch: $ref"
		if [ "$ref" = "$FOLD" ]; then
			echo "series: a rewrite of sm6450; apply onto the base in place of kernel/patches"
		else
			echo "series: $series"
		fi
		echo "tip:    $(git -C "$TREE" rev-parse "$ref")"
		echo "base:   $base $(git -C "$TREE" log -1 --format=%s "$base")"
		echo "        (git describe: $(git -C "$TREE" describe --tags "$base" 2>/dev/null || echo none))"
		echo "patches: $n"
		# A branch cut from an older version of the series sits on
		# commits sm6450 has since rewritten. They are not exported,
		# because sm6450 has their equivalents, so these patches apply
		# onto the series rather than onto the bare base above.
		if [ "$under" -gt 0 ]; then
			echo "under:  $under commits between base and these, on $series under other SHAs"
		fi
	} > "$dest/BASE"
	echo "$ref: $n"
done
