import collections
import os
import sys
from HTMLParser import HTMLParser
from collections import defaultdict
import json


class CoverageParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.values = []
        self.found_value = False

    def handle_starttag(self, tag, attrs):
        if tag == 'td':
            for attr_name, attr_value in attrs:
                if attr_name == 'class' and attr_value == 'headerTableEntry':
                    self.found_value = True
    
    def handle_data(self, data):
        if self.found_value:
            self.values.append(data)
            self.found_value = False

    def get_coverage_value(self):
        for value in self.values:
            if '%' in value:
                return value.strip('%').strip()


def get_coverage_value(html_path):
    with open(html_path, 'r') as html_content:
        parser = CoverageParser()
        parser.feed(html_content.read())
        return parser.get_coverage_value()


def main(results_path):
    coverage_map = {
        'runDate': {},
        'testArea': {},
        'latestRuns': {}
    }

    coverage_values = defaultdict(dict)

    time_dirs = os.listdir(results_path)
    for time_dir in time_dirs:
        area_dirs = os.listdir(os.path.join(results_path, time_dir))
        for area_dir in area_dirs:
            coverage_value = get_coverage_value(os.path.join(results_path, time_dir, area_dir, '%s.html' % area_dir))
            area_list = coverage_map['testArea'].get(area_dir, [])
            area_list.append([time_dir, coverage_value])
            coverage_map['testArea'][area_dir] = area_list

            time_list = coverage_map['runDate'].get(time_dir, [])
            time_list.append([area_dir, coverage_value])
            coverage_map['runDate'][time_dir] = time_list
            coverage_values[time_dir][area_dir] = coverage_value

    with open('pageData.js', 'w') as pageData:
        pageData.write("var testData = {};".format(coverage_map))


def append(json_path, results_path, kernel_value):
    latestresults = dict()
    data = json.load(open(json_path))
    time_value = os.path.basename(os.path.normpath(results_path))
    area_dirs = os.listdir(results_path)
    for area_dir in area_dirs:
        coverage_value = get_coverage_value(os.path.join(results_path, area_dir, '%s.html' % area_dir))
        area_list = data['testArea'].get(area_dir, [])
        test_val = (time_value, coverage_value)
        area_list.insert(0, test_val)
        data['testArea'][area_dir] = area_list
        
        time_list = data['runDate'].get(time_value, [])
        time_list.insert(0, [area_dir, coverage_value])
        data['runDate'][time_value] = time_list
        data['runDate'] = collections.OrderedDict(sorted(data['runDate'].items(), reverse=True))
        latestresults[area_dir] = (coverage_value, time_value)
        data['latestCoverage'] = latestresults
    
    data['kernelVersions'][time_value] = kernel_value
    print("var testData = " + json.dumps(data, indent=4, separators=(',', ': ')) + ";")
    exit(0)

if len(sys.argv) == 4:
    append(sys.argv[1], sys.argv[2], sys.argv[3])
else:
    main(sys.argv[1])