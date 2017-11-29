## ESPA Elevation Generation Version 2.3.1 - Release Notes

See git tag [v2.3.1]

This project contains application source code for extracting elevation data from external sources and generating an elevation product conforming to the input data. An option exists to specify a user-defined geographic extents (versus the default scene extents) to produce elevation for a different footprint from the scene.

### Support Information
This project is unsupported software provided by the U.S. Geological Survey (USGS) Earth Resources Observation and Science (EROS) Land Satellite Data Systems (LSDS) Project. For questions regarding products produced by this source code, please contact the Landsat Contact Us page and specify USGS Level-2 in the "Regarding" section. https://landsat.usgs.gov/contactus.php

### Disclaimer
This software is preliminary or provisional and is subject to revision. It is being provided to meet the need for timely best science. The software has not received final approval by the U.S. Geological Survey (USGS). No warranty, expressed or implied, is made by the USGS or the U.S. Government as to the functionality of the software and related material nor shall the fact of release constitute any such warranty. The software is provided on the condition that neither the USGS nor the U.S. Government shall be held liable for any damages resulting from the authorized or unauthorized use of the software.

## Release Notes
* Version changes
* Fixed a bug in the ARD handling regarding the min/max extents.  The code
  assumed these were reported for the center of the pixel, but they are
  actually for the UL corner of the pixel.  The fix involves checking the
  grid_origin and only adjusts the min/max extents for warping if the origin
  is for the CENTER of the pixel.

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
