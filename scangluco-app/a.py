import streamlit as st
import google.generativeai as genai
from PIL import Image
import io
import json
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# Configure Gemini API
GOOGLE_API_KEY = ""
genai.configure(api_key=GOOGLE_API_KEY)

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = ""
if 'patients_data' not in st.session_state:
    st.session_state.patients_data = {}

# Page configuration
st.set_page_config(
    page_title="Glucometer Reading Detection System",
    page_icon="🩸",
    layout="wide"
)

def detect_glucose_reading(image):
    """Use Gemini API to detect glucose readings from image"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = """
        Analyze this glucometer/glucose meter image carefully and extract the following information:
        
        1. Primary glucose reading value (the large number displayed)
        2. Unit of measurement (mg/dL, mmol/L, or %)
        3. Type of reading (Blood Glucose, HbA1c, etc.)
        4. Date and time if visible
        5. Any additional readings or indicators shown
        
        Respond in the following JSON format only:
        {
            "glucose_value": "numerical value only",
            "unit": "unit of measurement",
            "reading_type": "type of glucose reading",
            "date": "date if visible, else null",
            "time": "time if visible, else null",
            "additional_info": "any other relevant information"
        }
        
        Be precise and only extract what is clearly visible. If you cannot read something, mark it as null.
        """
        
        response = model.generate_content([prompt, image])
        
        # Extract JSON from response
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:-3]
        elif response_text.startswith('```'):
            response_text = response_text[3:-3]
        
        result = json.loads(response_text)
        return result, None
        
    except Exception as e:
        return None, str(e)

def save_patient_record(patient_id, name, age, glucose_data):
    """Save patient record to session state"""
    if patient_id not in st.session_state.patients_data:
        st.session_state.patients_data[patient_id] = {
            'name': name,
            'age': age,
            'readings': []
        }
    
    # Add new reading
    reading_entry = {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'uploaded_by': st.session_state.username,
        **glucose_data
    }
    
    st.session_state.patients_data[patient_id]['readings'].append(reading_entry)

def get_health_status(glucose_value, reading_type):
    """Determine health status based on glucose value"""
    try:
        value = float(glucose_value)
        
        if reading_type == "HbA1c" or "A1c" in reading_type:
            if value < 5.7:
                return "Normal", "🟢", "Good diabetes control"
            elif value < 6.5:
                return "Prediabetes", "🟡", "Increased risk - consult doctor"
            else:
                return "Diabetes", "🔴", "Requires medical attention"
        
        else:  # Blood glucose
            if value < 70:
                return "Low (Hypoglycemia)", "🔴", "Immediate attention needed"
            elif value <= 100:
                return "Normal (Fasting)", "🟢", "Healthy range"
            elif value <= 125:
                return "Prediabetes Range", "🟡", "Monitor closely"
            else:
                return "High (Hyperglycemia)", "🔴", "Consult healthcare provider"
    except:
        return "Unknown", "⚪", "Unable to determine"

def analyze_patient_data(patient_id):
    """Generate comprehensive analysis for a patient"""
    if patient_id not in st.session_state.patients_data:
        return None
    
    patient = st.session_state.patients_data[patient_id]
    readings = patient['readings']
    
    if not readings:
        return None
    
    # Convert to DataFrame for analysis
    df = pd.DataFrame(readings)
    
    analysis = {
        'patient_info': {
            'name': patient['name'],
            'age': patient['age'],
            'total_readings': len(readings)
        },
        'latest_reading': readings[-1],
        'readings_df': df
    }
    
    return analysis

# Login Page
def login_page():
    st.title("🩸 Glucometer Reading Detection System")
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.subheader("Login")
        username = st.text_input("Enter your name:", key="login_username")
        
        if st.button("Login", use_container_width=True):
            if username.strip():
                st.session_state.logged_in = True
                st.session_state.username = username.strip()
                st.rerun()
            else:
                st.error("Please enter your name")

# Main Application
def main_app():
    st.title(f"🩸 Glucometer Reading Detection System")
    st.markdown(f"**Welcome, {st.session_state.username}!**")
    
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page:",
        ["Upload Reading", "Patient Dashboard", "All Patients"]
    )
    
    if page == "Upload Reading":
        upload_reading_page()
    elif page == "Patient Dashboard":
        dashboard_page()
    else:
        all_patients_page()

def upload_reading_page():
    st.header("📤 Upload Glucometer Reading")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Patient Information")
        patient_id = st.text_input("Patient ID*", placeholder="e.g., P001")
        patient_name = st.text_input("Patient Name*", placeholder="e.g., John Doe")
        patient_age = st.number_input("Patient Age*", min_value=1, max_value=120, value=30)
    
    st.markdown("---")
    
    # Image upload options
    st.subheader("Upload Glucometer Image")
    
    upload_method = st.radio(
        "Choose upload method:",
        ["Upload Image File", "Capture from Camera"]
    )
    
    image = None
    
    if upload_method == "Upload Image File":
        uploaded_file = st.file_uploader(
            "Choose an image of the glucometer...",
            type=['png', 'jpg', 'jpeg']
        )
        if uploaded_file:
            image = Image.open(uploaded_file)
    else:
        camera_image = st.camera_input("Take a picture of the glucometer")
        if camera_image:
            image = Image.open(camera_image)
    
    if image:
        col1, col2 = st.columns(2)
        
        with col1:
            st.image(image, caption="Uploaded Image", use_container_width=True)
        
        with col2:
            if st.button("🔍 Detect Reading", use_container_width=True):
                if not patient_id or not patient_name:
                    st.error("Please fill in Patient ID and Name")
                else:
                    with st.spinner("Analyzing image with AI..."):
                        result, error = detect_glucose_reading(image)
                        
                        if error:
                            st.error(f"Error: {error}")
                        elif result:
                            st.success("✅ Reading detected successfully!")
                            
                            # Display results
                            st.subheader("Detected Information:")
                            
                            glucose_value = result.get('glucose_value', 'N/A')
                            unit = result.get('unit', 'N/A')
                            reading_type = result.get('reading_type', 'Blood Glucose')
                            
                            st.metric(
                                label=f"{reading_type}",
                                value=f"{glucose_value} {unit}"
                            )
                            
                            # Health status
                            status, emoji, message = get_health_status(glucose_value, reading_type)
                            st.info(f"{emoji} **Status:** {status}\n\n{message}")
                            
                            # Additional info
                            with st.expander("Additional Details"):
                                st.json(result)
                            
                            # Save record
                            if st.button("💾 Save Record", use_container_width=True):
                                save_patient_record(
                                    patient_id,
                                    patient_name,
                                    patient_age,
                                    result
                                )
                                st.success(f"✅ Record saved for Patient ID: {patient_id}")
                                st.balloons()

def dashboard_page():
    st.header("📊 Patient Dashboard")
    
    patient_id = st.text_input("Enter Patient ID to view analysis:", placeholder="e.g., P001")
    
    if st.button("Load Patient Data"):
        if patient_id in st.session_state.patients_data:
            analysis = analyze_patient_data(patient_id)
            
            if analysis:
                # Patient Info
                st.subheader("Patient Information")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Name", analysis['patient_info']['name'])
                with col2:
                    st.metric("Age", analysis['patient_info']['age'])
                with col3:
                    st.metric("Total Readings", analysis['patient_info']['total_readings'])
                
                st.markdown("---")
                
                # Latest Reading
                st.subheader("Latest Reading")
                latest = analysis['latest_reading']
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        "Glucose Level",
                        f"{latest.get('glucose_value', 'N/A')} {latest.get('unit', '')}"
                    )
                with col2:
                    st.metric("Reading Type", latest.get('reading_type', 'N/A'))
                with col3:
                    st.metric("Recorded", latest.get('timestamp', 'N/A'))
                
                status, emoji, message = get_health_status(
                    latest.get('glucose_value', '0'),
                    latest.get('reading_type', '')
                )
                st.info(f"{emoji} **Status:** {status}\n\n{message}")
                
                st.markdown("---")
                
                # Readings History
                st.subheader("Reading History")
                df = analysis['readings_df']
                
                # Convert glucose_value to numeric for plotting
                df['glucose_numeric'] = pd.to_numeric(df['glucose_value'], errors='coerce')
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                # Plot glucose trends
                if not df['glucose_numeric'].isna().all():
                    fig = go.Figure()
                    
                    fig.add_trace(go.Scatter(
                        x=df['timestamp'],
                        y=df['glucose_numeric'],
                        mode='lines+markers',
                        name='Glucose Level',
                        line=dict(color='#FF6B6B', width=3),
                        marker=dict(size=10)
                    ))
                    
                    fig.update_layout(
                        title="Glucose Level Trend",
                        xaxis_title="Date & Time",
                        yaxis_title=f"Glucose Level ({df['unit'].iloc[0]})",
                        hovermode='x unified',
                        height=400
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                
                # Display table
                st.dataframe(
                    df[['timestamp', 'glucose_value', 'unit', 'reading_type', 'uploaded_by']],
                    use_container_width=True
                )
                
                # Download option
                csv = df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Report as CSV",
                    data=csv,
                    file_name=f"patient_{patient_id}_report.csv",
                    mime="text/csv"
                )
        else:
            st.warning(f"No data found for Patient ID: {patient_id}")

def all_patients_page():
    st.header("👥 All Patients")
    
    if not st.session_state.patients_data:
        st.info("No patient records available yet.")
    else:
        # Create summary table
        summary_data = []
        for pid, data in st.session_state.patients_data.items():
            latest_reading = data['readings'][-1] if data['readings'] else {}
            summary_data.append({
                'Patient ID': pid,
                'Name': data['name'],
                'Age': data['age'],
                'Total Readings': len(data['readings']),
                'Latest Reading': latest_reading.get('glucose_value', 'N/A'),
                'Unit': latest_reading.get('unit', ''),
                'Last Updated': latest_reading.get('timestamp', 'N/A')
            })
        
        df_summary = pd.DataFrame(summary_data)
        st.dataframe(df_summary, use_container_width=True)
        
        # Statistics
        st.subheader("Statistics")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Patients", len(st.session_state.patients_data))
        with col2:
            total_readings = sum(len(p['readings']) for p in st.session_state.patients_data.values())
            st.metric("Total Readings", total_readings)
        with col3:
            avg_readings = total_readings / len(st.session_state.patients_data) if st.session_state.patients_data else 0
            st.metric("Avg Readings/Patient", f"{avg_readings:.1f}")

# Main execution
if not st.session_state.logged_in:
    login_page()
else:

    main_app()
