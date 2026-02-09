import streamlit as st
import subprocess
import sys
import os
import tempfile
import pandas as pd

# Path to the script
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), 'channels_to_description.py')

st.title("YouTube Channel Descriptions Extractor")

st.markdown("""
Upload a CSV with columns: video_url, video_title, channel_url, channel_name.
This tool will add a 'channel_description' column by scraping YouTube channels.
""")

uploaded_file = st.file_uploader("Upload input CSV", type=['csv'])

if uploaded_file is not None:
    # Display preview
    df = pd.read_csv(uploaded_file)
    st.write("Preview of uploaded CSV:")
    st.dataframe(df.head())

    if st.button("Extract Descriptions"):
        with st.spinner("Processing... This may take a while."):
            # Save uploaded file to temp
            with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp_in:
                tmp_in.write(uploaded_file.getvalue())
                input_path = tmp_in.name

            # Output path
            output_path = input_path.replace('.csv', '_with_descriptions.csv')

            # Run the script
            cmd = [sys.executable, SCRIPT_PATH, '--input', input_path, '--output', output_path]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(SCRIPT_PATH))

            if result.returncode == 0:
                st.success("Extraction completed!")
                # Load and display output
                output_df = pd.read_csv(output_path)
                st.write("Output CSV preview:")
                st.dataframe(output_df.head())

                # Download button
                with open(output_path, 'rb') as f:
                    st.download_button(
                        label="Download Output CSV",
                        data=f,
                        file_name="channels_with_descriptions.csv",
                        mime="text/csv"
                    )
            else:
                st.error("Error during extraction:")
                st.text(result.stderr)
                st.text(result.stdout)