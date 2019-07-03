# pycambot
## Overview
The goal of `pycambot` is to replace a human camera operator with an autonomous pan-tilt-zoom camera.  The application it was designed for is live streaming of a human speaker, with the speaker moving against a static background, and no other subjects in motion. 

The bot uses OpenCV native face detection to identify the subject. It will revert to a safe PTZ position if it loses the subject's face for a few seconds.

The only camera tested with `pycambot` so far is the PTZOptics 20xUSB. The solution was tested on a UDOO x86 SOC board, an Intel all-in-one board with the processing power to capture HD video via a USB 3.0 interface and run it through OpenCV libraries at a reasonable frame rate.

## Setup
If you are new to OpenCV, save yourself some time and use Docker images for kickstarting your environment. I recommend running Docker on Ubuntu and using [one of these images](https://hub.docker.com/r/victorhcm/opencv/). But first read the [excellent tutorial](http://www.pyimagesearch.com/2016/10/24/ubuntu-16-04-how-to-install-opencv/) from whose steps the Docker image was constructed.

## Solution elements:
+ Python 2.7
+ OpenCV 3.2
+ HD PTZ camera supporting VISCA over serial and USB 3.0 HD video transfer

## Tổng quát hệ thống
Mục đích của hệ thống là tự động di chuyển camera theo dõi khuôn mặt (hoặc vật thể ) dựa vào pan-tilt-zoom. Ứng dụng này thiết kế cho việc live-stream của 1 speaker(diễn giả). Khi người này di chuyển qua lại trên sân khấu, camera sẽ tự động di chuyển góc máy sao cho khuôn mặt của diễn giả luôn ở phần trung tâm của camera mà không cần tác động thủ công nào

## Chuẩn bị
### Phần cứng
- 1 camera ptz dùng giao tiếp visca command (rs232 và rs422). Trong hệ thống này mình sử dụng camera SONY EVI-D80P giao tiếp qua cổng rs232
- 1 laptop sử dụng hệ điều hành nhân linux. Mình sử dụng ubuntu 18.04, có thể sử dụng win or macos nhưng sẽ có nhiều vấn đề cần xử lí ở code và kết nối phần cứng nên k recommend
- 1 cap kết nối VISCA-to-usb để giao tiếp camera với laptop và 1 cap sVideo-to-usb để stream video từ video đến lap
### Phần mềm
- mình sử dụng thư viện pysca (clone từ bitbucket : https://bitbucket.org/uni-koeln/pysca) để lấy các hàm API điều khiển camera từ laptop biên dịch từ visca command sang python.ngoài ra còn sử dụng OpenCV3.2 để sử dụng nhận diện khuôn mặt và 1 số thư viện hỗ trợ. Tất cả đều dùng trên Python ver2.7
- Run hệ thống :gõ trên terminal :  python cambot.py


### Các hàm sử dụng
- pan_tilt (device, pan=None, tilt=None, pan_position=None, tilt_position=None, relative=False, blocking=False) : hàm API điều khiển camera
+ device : param truyền vào mặc định bằng 1
+ pan : giá trị chạy từ -12 => 12, dùng để điều chỉnh tốc độ quay ngang của camera ( từ 0 đến 12), nếu âm camera sẽ quay sang trái, nếu dương camera sẽ quay sang phải
+ tilt : giá trị chạy từ -12 => 12, dùng để điều chỉnh tốc độ quay dọc của camera ( từ 0 đến 12), nếu âm camera sẽ quay xuống dưới, nếu dương camera sẽ quay lên trên
+ các param còn lại có thể để măc định (tham khảo thêm tại pysca.py)

 
 
