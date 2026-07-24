import os
import subprocess
import time

def capture_html_screenshot(html_path: str, output_png_path: str):
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    abs_html = os.path.abspath(html_path)
    abs_out = os.path.abspath(output_png_path)
    
    file_uri = f"file:///{abs_html.replace('\\', '/')}"
    
    cmd = [
        edge_path,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1280,2400",
        f"--screenshot={abs_out}",
        file_uri
    ]
    
    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("Return code:", res.returncode)
    print("Output PNG exists:", os.path.exists(abs_out))
    if os.path.exists(abs_out):
        print("PNG size bytes:", os.path.getsize(abs_out))

if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')
    from pipeline.query_engine.selective_fetcher import QuestionFetcher
    from pipeline.report_generator.html_builder import HTMLReportBuilder
    
    fetcher = QuestionFetcher()
    item = fetcher.get_question("202606_MATH_DIF_15")
    builder = HTMLReportBuilder()
    builder.build_report(item, save=True, enforce_completeness=True)
    
    capture_html_screenshot("storage/html_reports/202606_MATH_DIF_15_report.html", "storage/html_reports/report_preview.png")
