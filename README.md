## ESPA Elevation Generation Version 2.0.1 - Release Notes

Release Date: August 2016

See git tag [v2.0.1]

This project contains application source code for extracting elevation data from external sources and generating an elevation product conforming to the input data.

### External Elevation Datasets
* GTOPO30
* GLS
* RAMP

## Release Notes
* Initial project version
* Migrated from original source location to this project
* Minor changes for collection based processing

## Installation

### Dependencies
* Python 2.7.X
* [espa-python-library](https://github.com/USGS-EROS/espa-python-library) 1.0.1
* [GDAL](http://www.gdal.org/) 1.11.1
  - The command line tools are utilized for some of the processing steps.

### Environment Variables
```
export ESPA_ELEVATION_DIR="path_to_External_Elevation_Datasets"
```

### Build Steps
```
make install
```

## Usage
See `build_elevation_band.py --help` for command line details.

### Data Processing Requirements
This version of the Land Surface Temperature application requires the input products to be in the ESPA internal file format.

The following input data are required to generate the elevation product:
* Level 1 Source Data
  - The reflectance band 1 information present in the XML metadata file to allow for determining source elevation and extent information so that the generated elevation product matches the input data.
* External Elevation
  - The external elevation data is expected to be available and in the proper formats to allow for extraction, mosaicing, and final elevation product generation.

### Data Postprocessing
After compiling the [espa-product-formatter](https://github.com/USGS-EROS/espa-product-formatter) libraries and tools, the `convert_espa_to_gtif` and `convert_espa_to_hdf` command-line tools can be used to convert the ESPA internal file format to HDF or GeoTIFF.  Otherwise the data will remain in the ESPA internal file format, which includes each band in the ENVI file format (i.e. raw binary file with associated ENVI header file) and an overall XML metadata file.

## More Information
This project is provided by the US Geological Survey (USGS) Earth Resources Observation and Science (EROS) Land Satellite Data Systems (LSDS) Science Research and Development (LSRD) Project. For questions regarding products produced by this source code, please contact the Landsat Contact Us page and specify USGS CDR/ECV in the "Regarding" section. https://landsat.usgs.gov/contactus.php
