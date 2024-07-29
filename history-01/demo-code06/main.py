import cv2
import mediapipe as mp
import numpy as np
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import csv
import os
from threading import Thread

class PoseEstimation:
    def __init__(self):
        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils
        self.templates = {"upper_body": [], "lower_body": []}
        self.recording = False
        self.keypoints_data = []
        self.video_playing = False
        self.video_length = 0
        self.current_frame = 0
        self.TEMPLATES_FILE = 'templates.csv'
        self.template_match_counts = {"upper_body": {}, "lower_body": {}}
        self.dragging = False
        self.last_matched_templates = {"upper_body": set(), "lower_body": set()}
        self.video_path = os.path.join('../..', 'mp4', '01.mp4')
        self.load_templates_from_csv()

    def draw_skeleton(self, image, keypoints, connections, color, circle_radius=2):
        for connection in connections:
            start_idx = connection[0]
            end_idx = connection[1]
            if start_idx < len(keypoints) and end_idx < len(keypoints) and start_idx > 10 and end_idx > 10:
                start_point = (
                    int(keypoints[start_idx][0] * image.shape[1]), int(keypoints[start_idx][1] * image.shape[0]))
                end_point = (int(keypoints[end_idx][0] * image.shape[1]), int(keypoints[end_idx][1] * image.shape[0]))
                cv2.line(image, start_point, end_point, color, 2)
                cv2.circle(image, start_point, circle_radius, color, -1)
                cv2.circle(image, end_point, circle_radius, color, -1)

        # Draw face triangle
        face_indices = [3, 6, 10, 9]
        if all(idx < len(keypoints) for idx in face_indices):
            points = [keypoints[idx][:2] for idx in face_indices]
            points = [(int(x * image.shape[1]), int(y * image.shape[0])) for x, y in points]
            triangle_cnt = np.array(points, np.int32).reshape((-1, 1, 2))
            cv2.drawContours(image, [triangle_cnt], 0, color, 2)

        # Draw connection line
        connection_indices = [9, 10, 11, 12]
        if all(idx < len(keypoints) for idx in connection_indices):
            points = [keypoints[idx][:2] for idx in connection_indices]
            points = [(int(x * image.shape[1]), int(y * image.shape[0])) for x, y in points]
            mouth_mid_point = ((points[0][0] + points[1][0]) // 2, (points[0][1] + points[1][1]) // 2)
            shoulder_mid_point = ((points[2][0] + points[3][0]) // 2, (points[2][1] + points[3][1]) // 2)
            cv2.line(image, mouth_mid_point, shoulder_mid_point, color, 2)

    def update_data_panel(self, panel, keypoints, match_results):
        for widget in panel.winfo_children():
            widget.destroy()

        total_matches = {category: sum(self.template_match_counts[category].values()) for category in self.template_match_counts}

        for category, templates in self.templates.items():
            frame = tk.Frame(panel)
            frame.pack(fill="both", expand=True, pady=5)
            title = tk.Label(frame, text=f"Category: {category}", font=("Arial", 14, "bold"))
            title.pack(anchor="w")

            for template in templates:
                template_name = template["name"]
                match_count = self.template_match_counts[category].get(template_name, 0)
                match_percentage = (match_count / total_matches[category] * 100) if total_matches[category] > 0 else 0
                match_info = tk.Label(frame, text=f"{template_name} Matches: {match_count} ({match_percentage:.2f}%)", font=("Arial", 12))
                match_info.pack(anchor="w")

    def draw_combined_image(self, template_keypoints_data, athlete_keypoints):
        frame = np.zeros((220, 200, 3), dtype=np.uint8)

        template_image = np.zeros((200, 200, 3), dtype=np.uint8)
        for keypoints in template_keypoints_data:
            self.draw_skeleton(template_image, keypoints, self.mp_pose.POSE_CONNECTIONS, (255, 255, 255), 3)

        athlete_image = np.zeros((200, 200, 3), dtype=np.uint8)
        self.draw_skeleton(athlete_image, athlete_keypoints, self.mp_pose.POSE_CONNECTIONS, (0, 255, 0), 3)

        combined_image = cv2.addWeighted(template_image, 0.5, athlete_image, 0.5, 0)

        # Convert to PIL image
        combined_image_pil = Image.fromarray(cv2.cvtColor(combined_image, cv2.COLOR_BGR2RGB))

        return combined_image_pil

    def resize_image_with_aspect_ratio(self, image, target_width, target_height):
        original_width, original_height = image.size
        if original_width == 0 or original_height == 0:
            return Image.new("RGB", (target_width, target_height))

        ratio = min(target_width / original_width, target_height / original_height)
        new_width = max(1, int(original_width * ratio))
        new_height = max(1, int(original_height * ratio))
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        new_image = Image.new("RGB", (target_width, target_height))
        new_image.paste(image, ((target_width - new_width) // 2, (target_height - new_height) // 2))
        return new_image

    def calculate_angle(self, a, b, c):
        a = np.array(a)
        b = np.array(b)
        c = np.array(c)

        ba = a - b
        bc = c - b

        cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc))
        angle = np.arccos(cosine_angle)
        return np.degrees(angle)

    def compare_keypoints(self, current_keypoints, template_keypoints, category, threshold=0.9):
        upper_body_indices = [11, 12, 13, 14, 15, 16]
        lower_body_indices = [23, 24, 25, 26, 27, 28]

        indices = upper_body_indices if category == "upper_body" else lower_body_indices

        for frame_keypoints in template_keypoints:
            if len(current_keypoints) != len(frame_keypoints):
                continue

            angles_current = []
            angles_template = []

            for idxs in [(11, 13, 15), (12, 14, 16), (23, 25, 27), (24, 26, 28), (11, 23, 25), (12, 24, 26)]:
                if idxs[0] in indices and idxs[1] in indices and idxs[2] in indices:
                    angles_current.append(self.calculate_angle(current_keypoints[idxs[0]], current_keypoints[idxs[1]],
                                                               current_keypoints[idxs[2]]))
                    angles_template.append(
                        self.calculate_angle(frame_keypoints[idxs[0]], frame_keypoints[idxs[1]], frame_keypoints[idxs[2]]))

            similarity = np.mean([1 - abs(a - b) / 180 for a, b in zip(angles_current, angles_template)])
            if similarity >= threshold:
                return similarity

        return 0

    def save_templates_to_csv(self):
        with open(self.TEMPLATES_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['name', 'category', 'data'])
            for category, templates in self.templates.items():
                for template in templates:
                    writer.writerow([template['name'], category, template['data']])

    def load_templates_from_csv(self):
        self.templates = {"upper_body": [], "lower_body": []}
        if os.path.exists(self.TEMPLATES_FILE):
            try:
                with open(self.TEMPLATES_FILE, mode='r') as file:
                    reader = csv.reader(file)
                    next(reader)
                    for row in reader:
                        name = row[0]
                        category = row[1]
                        data = eval(row[2])
                        self.templates[category].append({'name': name, 'data': data})
            except (IOError, csv.Error) as e:
                messagebox.showerror("Error", f"Failed to load templates from CSV: {e}")

    def update_template_listbox(self, listbox):
        listbox.delete(0, tk.END)
        for category, templates in self.templates.items():
            for template in templates:
                listbox.insert(tk.END, f"{template['name']} ({category})")

    def update_video_panel(self, image, panel):
        window_width = left_frame_width
        window_height = int(screen_height * 0.85)
        if window_width > 0 and window_height > 0:
            image = self.resize_image_with_aspect_ratio(image, window_width, window_height)
            image = ImageTk.PhotoImage(image=image)
            panel.config(image=image)
            panel.image = image

    def process_video(self, frame, pose):
        match_results = {"upper_body": {}, "lower_body": {}}
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = pose.process(image)
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        keypoints = []

        if results.pose_landmarks:
            landmarks = results.pose_landmarks.landmark
            keypoints = [(lm.x, lm.y, lm.z) for lm in landmarks]
            match_results = self.match_all_templates(keypoints)
            self.draw_skeleton(image, keypoints, self.mp_pose.POSE_CONNECTIONS,
                               (0, 255, 0) if any(any(match_results[category].values()) for category in match_results) else (255, 255, 255))
            if self.recording:
                self.keypoints_data.append(keypoints)

        self.update_data_panel(data_panel, keypoints, match_results)
        self.update_combined_images(keypoints, match_results)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(image)
        return image

    def match_all_templates(self, current_keypoints):
        match_results = {"upper_body": {}, "lower_body": {}}
        current_matched_templates = {"upper_body": set(), "lower_body": set()}
        for category, templates in self.templates.items():
            for template in templates:
                template_name = template['name']
                template_keypoints = template['data']
                similarity = self.compare_keypoints(current_keypoints, template_keypoints, category)
                if similarity:
                    current_matched_templates[category].add(template_name)
                    if template_name not in self.last_matched_templates[category]:
                        if template_name not in self.template_match_counts[category]:
                            self.template_match_counts[category][template_name] = 0
                        self.template_match_counts[category][template_name] += 1
                match_results[category][template_name] = similarity
        self.last_matched_templates = current_matched_templates
        return match_results

    def analyze_video(self):
        def play_video_with_audio():
            cap = cv2.VideoCapture(self.video_path)
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                # Use a flag to safely call cv2.imshow in the main thread
                self.frame_to_show = frame
                self.new_frame = True
                if cv2.waitKey(1) & 0xFF == 27:  # ESC key to exit
                    break
            cap.release()
            cv2.destroyAllWindows()

        self.new_frame = False
        self.frame_to_show = None

        video_thread = Thread(target=play_video_with_audio)
        video_thread.start()

        cap = cv2.VideoCapture(self.video_path)
        self.keypoints_data = []
        self.video_length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame = 0
        self.video_playing = True

        with self.mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
            while cap.isOpened() and self.video_playing:
                if not self.dragging:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
                ret, frame = cap.read()
                if not ret:
                    break

                if not self.dragging:
                    self.current_frame += 1
                image = self.process_video(frame, pose)
                self.update_video_panel(image, video_panel)
                self.update_progress_bar()
                root.update_idletasks()
                root.update()

        self.video_playing = False
        cap.release()
        cv2.destroyAllWindows()

    def update_combined_images(self, keypoints, match_results):
        combined_image_width, combined_image_height = 200, 200
        placeholder_image = Image.new("RGB", (combined_image_width, combined_image_height), (255, 255, 255))
        upper_body_combined_image = ImageTk.PhotoImage(placeholder_image)
        lower_body_combined_image = ImageTk.PhotoImage(placeholder_image)

        upper_body_match_text = "Matching upper body template..."
        lower_body_match_text = "Matching lower body template..."

        for category, templates in self.templates.items():
            current_match = None
            current_similarity = 0
            for template in templates:
                template_name = template["name"]
                if match_results[category].get(template_name, False):
                    similarity = match_results[category][template_name]
                    if similarity > current_similarity:
                        current_similarity = similarity
                        current_match = template
            if current_match:
                combined_image = self.draw_combined_image(current_match["data"], keypoints)
                combined_image = self.resize_image_with_aspect_ratio(combined_image, combined_image_width, combined_image_height)
                combined_image_tk = ImageTk.PhotoImage(combined_image)
                if category == "upper_body":
                    upper_body_combined_image = combined_image_tk
                    upper_body_match_text = f"{current_match['name']} (Similarity: {current_similarity:.2f})"
                else:
                    lower_body_combined_image = combined_image_tk
                    lower_body_match_text = f"{current_match['name']} (Similarity: {current_similarity:.2f})"

        upper_body_match_label.config(text=upper_body_match_text)
        upper_body_image_label.config(image=upper_body_combined_image)
        upper_body_image_label.image = upper_body_combined_image
        lower_body_match_label.config(text=lower_body_match_text)
        lower_body_image_label.config(image=lower_body_combined_image)
        lower_body_image_label.image = lower_body_combined_image

    def update_progress_bar(self):
        if self.video_length > 0:
            progress = (self.current_frame / self.video_length) * 100
            progress_var.set(progress)

    def play_template_video(self, template_data):
        self.video_playing = True
        self.video_length = len(template_data)
        self.current_frame = 0

        for keypoints in template_data:
            if not self.video_playing:
                break

            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            self.draw_skeleton(frame, keypoints, self.mp_pose.POSE_CONNECTIONS, (255, 255, 255), 3)
            image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(image)
            self.update_video_panel(image, video_panel)
            self.update_progress_bar()
            self.current_frame += 1
            root.update_idletasks()
            root.update()

        self.video_playing = False

    def start_real_time_analysis(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(0)
        self.template_match_counts = {"upper_body": {}, "lower_body": {}}
        self.video_playing = True

class PoseApp:
    def __init__(self, root, pose_estimation):
        self.root = root
        self.pose_estimation = pose_estimation
        self.cap = cv2.VideoCapture(0)
        self.mode = "real_time"
        self.setup_ui()

    def setup_ui(self):
        self.root.title("Pose Estimation and Analysis")
        self.root.state('zoomed')
        global screen_width, screen_height, left_frame_width, right_frame_width, progress_var
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        left_frame_width = int(screen_width * 0.68)
        right_frame_width = screen_width - left_frame_width

        self.left_frame = ttk.Frame(self.root, width=left_frame_width, height=screen_height)
        self.left_frame.pack(side="left", fill="y", expand=False)

        global mode_label
        mode_label = tk.Label(self.left_frame, text="Mode: Real-time Analysis", bg="green", fg="white",
                              font=("Arial", 16))
        mode_label.pack(side="top", fill="x")

        self.top_left_frame = ttk.Frame(self.left_frame, width=left_frame_width, height=int(screen_height * 0.85),
                                        relief="solid", borderwidth=1)
        self.top_left_frame.pack(side="top", fill="both", expand=True)

        global video_panel
        video_panel = tk.Label(self.top_left_frame)
        video_panel.pack(fill="both", expand=True)

        self.progress_frame = ttk.Frame(self.left_frame, width=left_frame_width, height=20)
        self.progress_frame.pack(side="top", fill="x")

        progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Scale(self.progress_frame, from_=0, to=100, orient="horizontal", variable=progress_var,
                                      command=self.on_progress_bar_drag)
        self.progress_bar.pack(fill="x", expand=True)
        self.progress_bar.bind("<ButtonRelease-1>", self.on_progress_bar_release)
        self.progress_bar.bind("<ButtonPress-1>", self.on_progress_bar_press)

        self.right_frame = ttk.Frame(self.root, width=right_frame_width, height=screen_height)
        self.right_frame.pack(side="right", fill="both", expand=True)

        self.top_frame = ttk.Frame(self.right_frame, width=right_frame_width, height=int(screen_height * 0.4),
                                   relief="solid", borderwidth=1)
        self.top_frame.pack(side="top", fill="both", expand=True)

        global upper_body_match_label
        upper_body_match_label = tk.Label(self.top_frame, font=("Arial", 24, "bold"), fg="green")
        upper_body_match_label.pack(side="top", fill="x", padx=5, pady=5)

        global upper_body_image_label
        upper_body_image_label = tk.Label(self.top_frame)
        upper_body_image_label.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        global lower_body_match_label
        lower_body_match_label = tk.Label(self.top_frame, font=("Arial", 24, "bold"), fg="green")
        lower_body_match_label.pack(side="top", fill="x", padx=5, pady=5)

        global lower_body_image_label
        lower_body_image_label = tk.Label(self.top_frame)
        lower_body_image_label.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        global data_panel
        data_panel = ttk.Frame(self.right_frame)
        data_panel.pack(side="top", fill="both", expand=True)

        self.bottom_frame = ttk.Frame(self.right_frame, width=right_frame_width, height=int(screen_height * 0.25),
                                      relief="solid", borderwidth=1)
        self.bottom_frame.pack(side="bottom", fill="both", expand=True)

        template_list_label = tk.Label(self.bottom_frame, text="Saved Templates", justify=tk.LEFT, anchor="nw",
                                       font=("Arial", 12, "bold"))
        template_list_label.pack(side="top", fill="x", pady=5)

        global template_listbox
        template_listbox = tk.Listbox(self.bottom_frame, height=3)
        template_listbox.pack(side="top", fill="both", expand=True)

        instruction_label = tk.Label(self.bottom_frame,
                                     text="Press 'r' to start real-time analysis using the webcam.\nPress 'a' to start creating an action template.\nPress 'd' to delete a selected template.\nPress 'o' to start matching action templates in the video.",
                                     justify=tk.LEFT, anchor="nw")
        instruction_label.pack(side="bottom", fill="x", expand=False)

        self.pose_estimation.load_templates_from_csv()
        self.pose_estimation.update_template_listbox(template_listbox)

        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.after(10, self.update_frame)

    def update_mode_label(self):
        mode_text = {
            "real_time": "Mode: Real-time Analysis",
            "analyze_video": "Mode: Analyze Video",
            "match_template": "Mode: Match Template"
        }
        mode_label.config(text=mode_text.get(self.mode, "Mode: Unknown"))

    def on_key_press(self, event):
        if event.keysym == 'Escape':
            self.root.destroy()
            self.cap.release()
            cv2.destroyAllWindows()
        elif event.keysym == 'a':
            self.mode = "analyze_video"
            self.update_mode_label()
            self.pose_estimation.analyze_video()
        elif event.keysym == 'b':
            self.pose_estimation.recording = True
            print("Recording started")
        elif event.keysym == 'e':
            self.pose_estimation.recording = False
            print("Recording stopped")
            if self.pose_estimation.keypoints_data:
                input_dialog = TemplateInputDialog(self.root)
                self.root.wait_window(input_dialog.dialog)
                if input_dialog.template_name and input_dialog.category:
                    self.pose_estimation.templates[input_dialog.category].append(
                        {"name": input_dialog.template_name, "data": self.pose_estimation.keypoints_data})
                    self.pose_estimation.keypoints_data = []
                    self.pose_estimation.update_template_listbox(template_listbox)
                    self.pose_estimation.save_templates_to_csv()
        elif event.keysym == 'r':
            self.mode = "real_time"
            self.update_mode_label()
            self.pose_estimation.start_real_time_analysis()
        elif event.keysym == 'd':
            selection = template_listbox.curselection()
            if selection:
                index = selection[0]
                selected_template = template_listbox.get(index)
                template_name, category = selected_template.rsplit(' (', 1)
                category = category.rstrip(')')
                self.pose_estimation.templates[category] = [t for t in self.pose_estimation.templates[category] if t['name'] != template_name]
                self.pose_estimation.update_template_listbox(template_listbox)
                self.pose_estimation.save_templates_to_csv()
        elif event.keysym == 'o':
            if any(self.pose_estimation.templates.values()):
                self.mode = "match_template"
                self.update_mode_label()
                self.pose_estimation.analyze_video()

    def update_frame(self):
        if not self.cap.isOpened():
            self.root.after(10, self.update_frame)
            return

        if self.mode == "real_time":
            ret, frame = self.cap.read()
            if ret:
                with self.pose_estimation.mp_pose.Pose(min_detection_confidence=0.5,
                                                       min_tracking_confidence=0.5) as pose:
                    image = self.pose_estimation.process_video(frame, pose)
                    self.pose_estimation.update_video_panel(image, video_panel)

        self.root.after(10, self.update_frame)

    def on_progress_bar_drag(self, value):
        self.pose_estimation.dragging = True
        if self.pose_estimation.video_length > 0:
            frame_number = int((float(value) / 100) * self.pose_estimation.video_length)
            self.pose_estimation.current_frame = frame_number
            self.update_video_to_frame(frame_number)

    def on_progress_bar_press(self, event):
        self.pose_estimation.dragging = True

    def on_progress_bar_release(self, event):
        self.pose_estimation.dragging = False

    def update_video_to_frame(self, frame_number):
        cap = cv2.VideoCapture(self.pose_estimation.video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if ret:
            with self.pose_estimation.mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
                image = self.pose_estimation.process_video(frame, pose)
                self.pose_estimation.update_video_panel(image, video_panel)
        cap.release()

class TemplateInputDialog:
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Input Template Information")
        self.dialog.geometry("300x225")  # Increase height by 1/2
        self.dialog.grab_set()

        # Center the dialog on the screen
        screen_width = self.dialog.winfo_screenwidth()
        screen_height = self.dialog.winfo_screenheight()
        x = (screen_width - 300) // 2
        y = (screen_height - 225) // 2
        self.dialog.geometry(f"+{x}+{y}")

        tk.Label(self.dialog, text="Template Name:").pack(pady=5)
        self.template_name_entry = tk.Entry(self.dialog)
        self.template_name_entry.pack(pady=5)

        tk.Label(self.dialog, text="Template Category:").pack(pady=5)
        self.category_var = tk.StringVar()
        self.category_combobox = ttk.Combobox(self.dialog, textvariable=self.category_var)
        self.category_combobox['values'] = ("upper_body", "lower_body")
        self.category_combobox.pack(pady=5)

        self.save_button = tk.Button(self.dialog, text="Save", command=self.save)
        self.save_button.pack(pady=5)

        self.template_name = None
        self.category = None

    def save(self):
        self.template_name = self.template_name_entry.get()
        self.category = self.category_var.get()
        self.dialog.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    pose_estimation = PoseEstimation()
    app = PoseApp(root, pose_estimation)
    root.mainloop()
