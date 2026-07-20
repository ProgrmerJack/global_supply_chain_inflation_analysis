import pandas as pd
import os
import glob
from datetime import datetime
import numpy as np

"""
Script to process Marine Cadastre AIS data.
This script reads raw AIS CSV files and constructs port-level metrics.

Expected input: data/raw/ais/*.csv (downloaded from marinecadastre.gov)
Output: data/processed/port_metrics.parquet
"""

# Configuration
RAW_AIS_DIR = "data/raw/ais"
OUTPUT_DIR = "data/processed"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Major US Ports (approximate bounding boxes)
PORTS = {
    "LA_Long_Beach": {"lat_min": 33.6, "lat_max": 33.9, "lon_min": -118.3, "lon_max": -118.1},
    "NY_NJ": {"lat_min": 40.6, "lat_max": 40.8, "lon_min": -74.2, "lon_max": -73.9},
    "Houston": {"lat_min": 29.6, "lat_max": 29.9, "lon_min": -95.4, "lon_max": -94.9},
    "Savannah": {"lat_min": 32.0, "lat_max": 32.2, "lon_min": -81.2, "lon_max": -80.9},
    "Seattle": {"lat_min": 47.5, "lat_max": 47.7, "lon_min": -122.5, "lon_max": -122.3},
}

def is_in_port(lat, lon, port_bounds):
    """Check if coordinates are within port bounds."""
    return (port_bounds["lat_min"] <= lat <= port_bounds["lat_max"] and
            port_bounds["lon_min"] <= lon <= port_bounds["lon_max"])

def process_ais_file(filepath, chunksize=100000):
    """
    Process a single AIS CSV file and extract port metrics.
    
    Returns:
        DataFrame with columns: [port, date, vessel_mmsi, dwell_time_hours, vessel_type]
    """
    print(f"Processing {filepath}...")
    
    # Expected columns (Marine Cadastre format)
    # MMSI,BaseDateTime,LAT,LON,SOG,COG,Heading,VesselName,IMO,CallSign,VesselType,Status,Length,Width,Draft,Cargo,TransceiverClass
    
    port_visits = []
    
    try:
        for chunk in pd.read_csv(filepath, chunksize=chunksize, 
                                   usecols=["MMSI", "BaseDateTime", "LAT", "LON", "VesselType", "SOG"],
                                   parse_dates=["BaseDateTime"]):
            
            # Filter for cargo vessels (VesselType 70-79 are cargo ships)
            chunk = chunk[chunk["VesselType"].between(70, 79, inclusive="both")]
            
            # Assign to ports
            for port_name, bounds in PORTS.items():
                mask = chunk.apply(lambda row: is_in_port(row["LAT"], row["LON"], bounds), axis=1)
                port_chunk = chunk[mask].copy()
                
                if len(port_chunk) > 0:
                    # Group by vessel (MMSI) and date
                    port_chunk["date"] = port_chunk["BaseDateTime"].dt.date
                    
                    # Estimate dwell time: count hours vessel is in port (assuming data is hourly or more frequent)
                    # Simplified: count unique timestamps per vessel per day
                    daily_counts = port_chunk.groupby(["MMSI", "date"]).size().reset_index(name="n_observations")
                    daily_counts["port"] = port_name
                    daily_counts["dwell_hours_est"] = daily_counts["n_observations"] * 0.5  # Assume 30-min intervals
                    
                    port_visits.append(daily_counts)
    
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return None
    
    if port_visits:
        return pd.concat(port_visits, ignore_index=True)
    return None

def aggregate_monthly_metrics(port_visits_df):
    """
    Aggregate daily port visits to monthly metrics.
    
    Returns:
        DataFrame: [port, year_month, avg_dwell_time, vessel_count, congestion_index]
    """
    port_visits_df["year_month"] = pd.to_datetime(port_visits_df["date"]).dt.to_period("M")
    
    monthly = port_visits_df.groupby(["port", "year_month"]).agg({
        "dwell_hours_est": ["mean", "median", "std"],
        "MMSI": "nunique"  # Unique vessels
    }).reset_index()
    
    monthly.columns = ["port", "year_month", "avg_dwell_hours", "median_dwell_hours", "std_dwell_hours", "unique_vessels"]
    
    # Congestion Index: Standardized dwell time
    # Higher dwell time = more congestion
    for port in monthly["port"].unique():
        mask = monthly["port"] == port
        mean_dwell = monthly.loc[mask, "avg_dwell_hours"].mean()
        std_dwell = monthly.loc[mask, "avg_dwell_hours"].std()
        monthly.loc[mask, "congestion_index"] = (monthly.loc[mask, "avg_dwell_hours"] - mean_dwell) / std_dwell
    
    return monthly

def main():
    """
    Main processing pipeline.
    """
    # Find all AIS CSV files
    ais_files = glob.glob(f"{RAW_AIS_DIR}/*.csv")
    
    if len(ais_files) == 0:
        print(f"No AIS files found in {RAW_AIS_DIR}/")
        print("Please download AIS data from Marine Cadastre and place CSV files in data/raw/ais/")
        print("See DATA_DOWNLOAD_INSTRUCTIONS.md for details.")
        return
    
    print(f"Found {len(ais_files)} AIS files")
    
    all_visits = []
    
    for filepath in ais_files[:5]:  # Process first 5 files (adjust as needed)
        result = process_ais_file(filepath)
        if result is not None:
            all_visits.append(result)
    
    if not all_visits:
        print("No valid data extracted.")
        return
    
    # Combine all
    port_visits = pd.concat(all_visits, ignore_index=True)
    print(f"Total port visits extracted: {len(port_visits)}")
    
    # Aggregate to monthly
    monthly_metrics = aggregate_monthly_metrics(port_visits)
    print(f"Monthly metrics shape: {monthly_metrics.shape}")
    print(monthly_metrics.head())
    
    # Save
    output_path = f"{OUTPUT_DIR}/port_congestion_metrics.parquet"
    monthly_metrics.to_parquet(output_path)
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    main()
