#!/bin/bash

GCDA=/sys/kernel/debug/gcov

while true;do
    case "$1" in
        --dest)
            DEST=$(readlink -f $2)
            shift 2;;
        --result)
            RESULT=$(readlink -f $2)
            shift 2;;
        --) shift; break ;;
        *) break ;;
    esac
done

echo "GCOV_MISSING" > $RESULT

if [ -z "$DEST" ] ; then
    echo "Missing destination parameter"
    echo "PARAM_MISSING" > $RESULT
    exit 0
fi

TEMPDIR=$(mktemp -d)
find $GCDA -type d -exec mkdir -p $TEMPDIR/\{\} \;
find $GCDA -name '*.gcda' -exec sh -c 'cat < $0 > '$TEMPDIR'/$0' {} \;
find $GCDA -name '*.gcno' -exec sh -c 'cp -d $0 '$TEMPDIR'/$0' {} \;
tar czf $DEST -C $TEMPDIR sys
rm -rf $TEMPDIR

echo "GCOV_COLLECTED" > $RESULT
exit 0
