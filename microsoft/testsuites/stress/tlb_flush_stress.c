/*
 * TLB Flush Stress Test
 * 
 * This program forces frequent TLB flushes by repeatedly unmapping and remapping
 * memory regions across multiple threads. It stresses the Translation Lookaside 
 * Buffer (TLB) to reveal performance degradation or instability under frequent 
 * virtual-to-physical remapping operations.
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <pthread.h>
#include <errno.h>
#include <string.h>
#include <time.h>
#include <signal.h>

#define PAGE_SIZE 4096
#define DEFAULT_THREADS 4
#define DEFAULT_PAGES_PER_THREAD 1024
#define DEFAULT_DURATION_SECONDS 60
#define DEFAULT_ITERATIONS_PER_CYCLE 100

static volatile int keep_running = 1;
static long total_tlb_flushes = 0;
static pthread_mutex_t counter_mutex = PTHREAD_MUTEX_INITIALIZER;

struct thread_data {
    int thread_id;
    int pages_per_thread;
    int duration_seconds;
    int iterations_per_cycle;
    long thread_tlb_flushes;
};

void signal_handler(int sig) {
    keep_running = 0;
}

void *tlb_flush_worker(void *arg) {
    struct thread_data *data = (struct thread_data *)arg;
    void **memory_regions;
    int i, j;
    time_t start_time, current_time;
    size_t region_size = data->pages_per_thread * PAGE_SIZE;
    
    printf("[Thread %d] Starting TLB flush stress with %d pages (%zu bytes)\n", 
           data->thread_id, data->pages_per_thread, region_size);
    
    // Allocate array to store memory region pointers
    memory_regions = malloc(sizeof(void*) * data->iterations_per_cycle);
    if (!memory_regions) {
        fprintf(stderr, "[Thread %d] Failed to allocate memory region array\n", 
                data->thread_id);
        return NULL;
    }
    
    start_time = time(NULL);
    data->thread_tlb_flushes = 0;
    
    while (keep_running) {
        current_time = time(NULL);
        if (current_time - start_time >= data->duration_seconds) {
            break;
        }
        
        // Phase 1: Allocate and map memory regions
        for (i = 0; i < data->iterations_per_cycle && keep_running; i++) {
            memory_regions[i] = mmap(NULL, region_size, 
                                   PROT_READ | PROT_WRITE,
                                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            
            if (memory_regions[i] == MAP_FAILED) {
                fprintf(stderr, "[Thread %d] mmap failed at iteration %d: %s\n", 
                        data->thread_id, i, strerror(errno));
                continue;
            }
            
            // Touch all pages to ensure they're mapped in TLB
            for (j = 0; j < data->pages_per_thread; j++) {
                volatile char *page = (char*)memory_regions[i] + (j * PAGE_SIZE);
                *page = (char)(i + j);  // Write to force page mapping
                __builtin_prefetch((const void*)page, 1, 0);  // Prefetch for write
            }
        }
        
        // Phase 2: Access patterns to stress TLB
        for (i = 0; i < data->iterations_per_cycle && keep_running; i++) {
            if (memory_regions[i] == MAP_FAILED) continue;
            
            // Random access pattern to maximize TLB pressure
            for (j = 0; j < data->pages_per_thread; j += 4) {
                int page_offset = (j * 17 + i * 13) % data->pages_per_thread;
                volatile char *page = (char*)memory_regions[i] + 
                                    (page_offset * PAGE_SIZE);
                char value = *page;  // Read access
                *page = value + 1;   // Write access
            }
        }
        
        // Phase 3: Unmap regions to force TLB flush
        for (i = 0; i < data->iterations_per_cycle && keep_running; i++) {
            if (memory_regions[i] == MAP_FAILED) continue;
            
            if (munmap(memory_regions[i], region_size) == -1) {
                fprintf(stderr, "[Thread %d] munmap failed at iteration %d: %s\n", 
                        data->thread_id, i, strerror(errno));
            } else {
                data->thread_tlb_flushes++;
            }
            memory_regions[i] = MAP_FAILED;
        }
        
        // Brief pause to allow system to process TLB flushes
        usleep(1000);  // 1ms
    }
    
    // Cleanup any remaining mapped regions
    for (i = 0; i < data->iterations_per_cycle; i++) {
        if (memory_regions[i] != MAP_FAILED) {
            munmap(memory_regions[i], region_size);
        }
    }
    
    free(memory_regions);
    
    pthread_mutex_lock(&counter_mutex);
    total_tlb_flushes += data->thread_tlb_flushes;
    pthread_mutex_unlock(&counter_mutex);
    
    printf("[Thread %d] Completed %ld TLB flush cycles\n", 
           data->thread_id, data->thread_tlb_flushes);
    
    return NULL;
}

void print_usage(const char *program_name) {
    printf("Usage: %s [OPTIONS]\n", program_name);
    printf("TLB Flush Stress Test - Forces frequent TLB flushes via memory mapping\n\n");
    printf("Options:\n");
    printf("  -t THREADS    Number of threads (default: %d)\n", DEFAULT_THREADS);
    printf("  -p PAGES      Pages per thread (default: %d)\n", DEFAULT_PAGES_PER_THREAD);
    printf("  -d DURATION   Test duration in seconds (default: %d)\n", DEFAULT_DURATION_SECONDS);
    printf("  -i ITERATIONS Iterations per cycle (default: %d)\n", DEFAULT_ITERATIONS_PER_CYCLE);
    printf("  -h            Show this help\n\n");
    printf("This test stresses the Translation Lookaside Buffer (TLB) by repeatedly\n");
    printf("mapping, accessing, and unmapping memory regions across multiple threads.\n");
}

int main(int argc, char *argv[]) {
    int num_threads = DEFAULT_THREADS;
    int pages_per_thread = DEFAULT_PAGES_PER_THREAD;
    int duration_seconds = DEFAULT_DURATION_SECONDS;
    int iterations_per_cycle = DEFAULT_ITERATIONS_PER_CYCLE;
    int opt;
    
    // Parse command line arguments
    while ((opt = getopt(argc, argv, "t:p:d:i:h")) != -1) {
        switch (opt) {
            case 't':
                num_threads = atoi(optarg);
                if (num_threads <= 0 || num_threads > 64) {
                    fprintf(stderr, "Invalid thread count: %d (1-64)\n", num_threads);
                    return 1;
                }
                break;
            case 'p':
                pages_per_thread = atoi(optarg);
                if (pages_per_thread <= 0 || pages_per_thread > 100000) {
                    fprintf(stderr, "Invalid pages per thread: %d (1-100000)\n", pages_per_thread);
                    return 1;
                }
                break;
            case 'd':
                duration_seconds = atoi(optarg);
                if (duration_seconds <= 0) {
                    fprintf(stderr, "Invalid duration: %d (must be > 0)\n", duration_seconds);
                    return 1;
                }
                break;
            case 'i':
                iterations_per_cycle = atoi(optarg);
                if (iterations_per_cycle <= 0 || iterations_per_cycle > 10000) {
                    fprintf(stderr, "Invalid iterations per cycle: %d (1-10000)\n", iterations_per_cycle);
                    return 1;
                }
                break;
            case 'h':
                print_usage(argv[0]);
                return 0;
            default:
                print_usage(argv[0]);
                return 1;
        }
    }
    
    printf("=== TLB Flush Stress Test ===\n");
    printf("Threads: %d\n", num_threads);
    printf("Pages per thread: %d (%d KB per thread)\n", 
           pages_per_thread, pages_per_thread * 4);
    printf("Duration: %d seconds\n", duration_seconds);
    printf("Iterations per cycle: %d\n", iterations_per_cycle);
    printf("Total memory per cycle: %ld MB\n", 
           (long)num_threads * pages_per_thread * iterations_per_cycle * 4 / 1024);
    printf("\nStarting TLB stress test...\n");
    
    // Set up signal handling
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    // Create thread data structures
    pthread_t *threads = malloc(sizeof(pthread_t) * num_threads);
    struct thread_data *thread_data = malloc(sizeof(struct thread_data) * num_threads);
    
    if (!threads || !thread_data) {
        fprintf(stderr, "Failed to allocate thread structures\n");
        return 1;
    }
    
    time_t test_start = time(NULL);
    
    // Start worker threads
    for (int i = 0; i < num_threads; i++) {
        thread_data[i].thread_id = i;
        thread_data[i].pages_per_thread = pages_per_thread;
        thread_data[i].duration_seconds = duration_seconds;
        thread_data[i].iterations_per_cycle = iterations_per_cycle;
        thread_data[i].thread_tlb_flushes = 0;
        
        if (pthread_create(&threads[i], NULL, tlb_flush_worker, &thread_data[i]) != 0) {
            fprintf(stderr, "Failed to create thread %d\n", i);
            keep_running = 0;
            break;
        }
    }
    
    // Wait for all threads to complete
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
    }
    
    time_t test_end = time(NULL);
    double actual_duration = difftime(test_end, test_start);
    
    printf("\n=== TLB Flush Stress Test Results ===\n");
    printf("Actual duration: %.1f seconds\n", actual_duration);
    printf("Total TLB flush cycles: %ld\n", total_tlb_flushes);
    printf("Average TLB flushes per second: %.2f\n", 
           total_tlb_flushes / actual_duration);
    printf("Average TLB flushes per thread: %.2f\n", 
           (double)total_tlb_flushes / num_threads);
    
    printf("\nTLB Flush Stress Test completed successfully.\n");
    
    free(threads);
    free(thread_data);
    
    return 0;
}