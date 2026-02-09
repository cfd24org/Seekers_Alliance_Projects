import streamlit as st
import subprocess
import sys
import os
import tempfile
import pandas as pd

# Path to the scripts
DISCOVER_SCRIPT = os.path.join(os.path.dirname(__file__), 'python_src', 'yt', 'youtube_discover_and_extract.py')
EXTRACT_SCRIPT = os.path.join(os.path.dirname(__file__), 'channels_to_description.py')

st.title("YouTube Tools")

st.markdown("Discover channels and extract descriptions.")

tab1, tab2 = st.tabs(["Discover Channels", "Extract Descriptions"])

with tab1:
    st.header("Discover YouTube Channels")
    
    query = st.text_input("Search Query", value="minecraft")
    max_channels = st.slider("Max Channels", min_value=1, max_value=50, value=20)
    collect_videos = st.checkbox("Collect Videos", value=False)
    output_path = st.text_input("Output CSV Path", value="outputs/yt_discover.csv")
    
    if st.button("Discover Channels"):
        with st.spinner("Discovering..."):
            cmd = [sys.executable, DISCOVER_SCRIPT, '--query', query, '--max-channels', str(max_channels), '--output', output_path]
            if collect_videos:
                cmd.append('--collect-videos')
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(__file__))
            
            if result.returncode == 0:
                st.success("Discovery completed!")
                st.text("Output: " + output_path)
                try:
                    df = pd.read_csv(output_path)
                    st.dataframe(df.head())
                except Exception:
                    st.error("Failed to load output CSV")
            else:
                st.error("Error during discovery:")
                st.text(result.stderr)
                st.text(result.stdout)

with tab2:
    st.header("Extract Channel Descriptions")
    
    st.markdown("Upload a CSV with columns: video_url, video_title, channel_url, channel_name.")
    
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
                output_path = os.path.join('outputs', 'channels_with_descriptions.csv')
                
                # Run the script
                cmd = [sys.executable, EXTRACT_SCRIPT, '--input', input_path, '--output', output_path]
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(__file__))
                
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