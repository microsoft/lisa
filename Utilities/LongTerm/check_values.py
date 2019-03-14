# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

import argparse
import csv
import os
import sys


def get_params():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv_path",
                        help="--csv_path <csv>")
    parser.add_argument("--check_columns",
                        help='--check_columns  "col1,col2"')
    params = parser.parse_args()

    if not os.path.isfile(params.csv_path):
        sys.exit("You need to specify an the path to the log csv")
    if not params.check_columns:
        sys.exit("You need to specify at least one column to be checked")

    return params

    
def main():
    max_delta = 10
    max_occurrence = 6

    params = get_params()
    
    csv_file = open(params.csv_path, "rb")
    csv_reader = csv.reader(csv_file)
    
    rows = []
    for row in csv_reader:
        rows.append(row)
    
    failed_colums = []
    
    columns = params.check_columns.split(",")
    for column in columns:
        if column not in rows[1]:
            print ("Error: Cannot find column in csv:" + column)
            exit(1)
        column_index = rows[1].index(column)
        index = 1
        sum = float(rows[9][column_index])
        occurrence = 0
        for row in rows[10:]:
            next_value = float(row[column_index])
            index = index + 1
            sum = sum + next_value
        
        avg = sum / index
        print (column + " average: " + str(avg))
        index = 10
        bad_values = []
        
        for row in rows[10:]:
            next_value = float(row[column_index])
            index = index + 1
            jitter = (avg * 100 / (next_value + 1))
            if (jitter > 100 + max_delta or jitter < 100 - max_delta):
                # print ("Index: " + str(index) + " Value: " + str(next_value) + " Jitter: " + str(jitter))
                occurrence = occurrence + 1
                bad_values.append("Time (min): " + str(index / 6) + " Value: " + str(next_value) + " Jitter: " + str(jitter))
            else:
                occurrence = 0
                bad_values = []
            if occurrence == max_occurrence:
                break
        
        if occurrence == max_occurrence:
            for value in bad_values:
                print (value)
            failed_colums.append(column)
            continue
            
    print ("Failed columns: " + str(failed_colums))
    report = ','.join(failed_colums)
    
    if report:
        with open("failed_values.txt", "w") as report_file:
            report_file.write(report)
        

main()
