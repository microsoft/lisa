#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <time.h>

int main(int argc, char *argv[]) {
    struct timespec start;
    unsigned long i;

    for (i=0; i<100000000UL; i++) {
        if( clock_gettime(CLOCK_REALTIME, &start) == -1 ) {
            perror( "clock gettime" );
            exit( EXIT_FAILURE );
        }
    }

    return 0;
}
