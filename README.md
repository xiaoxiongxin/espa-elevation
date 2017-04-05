## ESPA Elevation Generation Version 2.3.0 - Release Notes

See git tag [v2.3.0]

This project contains application source code for extracting elevation data from external sources and generating an elevation product conforming to the input data. An option exists to specify a user-defined geographic extents (versus the default scene extents) to produce elevation for a different footprint from the scene.

## Release Notes
* Version changes
* Added support for ARD Metadata

## Installation

### Dependencies
* Python 2.7.X and Numpy/GDAL
* [espa-python-library](https://github.com/USGS-EROS/espa-python-library) >= 1.1.0
* [GDAL](http://www.gdal.org/) 1.11.1
  - The command line tools are utilized for some of the processing steps.

### External Elevation Datasets
* GTOPO30
* GLS
* RAMP

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
This version of the Elevation Generation application requires the input XML Metadata to be in either the ESPA Metadata or ARD Metadata formats.

The following input data are required to generate the elevation product:
- For ESPA Metadata
  - Level 1 Source Data
    - The reflectance band 1 information present in the XML metadata file as well as on disk to allow for determining source elevation and extent information so that the generated elevation product matches the input data.
- For ARD Metadata
  - Level 2 Source Data
    - The pixel QA band information present in the XML metadata file as well as on disk to allow for determining source elevation and extent information so that the generated elevation product matches the input data.
- External Elevation
  - The external elevation data is expected to be available and in the proper formats to allow for extraction, mosaicing, and final elevation product generation.

### Data Postprocessing
After compiling the [espa-product-formatter](https://github.com/USGS-EROS/espa-product-formatter) libraries and tools, the `convert_espa_to_gtif` and `convert_espa_to_hdf` command-line tools can be used to convert the ESPA internal file format to HDF or GeoTIFF.  Otherwise the data will remain in the ESPA internal file format, which includes each band in the ENVI file format (i.e. raw binary file with associated ENVI header file) and an overall XML metadata file.

No tools exist for manipulating the resulting ARD products.

## More Information
This project is provided by the US Geological Survey (USGS) Earth Resources Observation and Science (EROS) Land Satellite Data Systems (LSDS) Science Research and Development (LSRD) Project. For questions regarding products produced by this source code, please contact the Landsat Contact Us page and specify USGS CDR/ECV in the "Regarding" section. https://landsat.usgs.gov/contactus.php
