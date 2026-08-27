# AMR 모델 선정

## **기준 기종:** Idealworks 사의 AMR, iw.hub

→  Idealworks: BMW 그룹의 물류 로보틱스 기업

![image1.png](image1.png)

#### AMR 사용 작업

![image2.png](image2.png)

![image3.png](image3.png)

#### **AMR 사양 및 성능**

![스크린샷 2026-08-26 124330.png](image4.png)

#### **AMR 연계 FMS/WMS/ERP/통신 → 기본적으로 VDA 5050을 따름**

![스크린샷 2026-08-26 143619.png](image5.png)

실제 벤더 사이트: [https://www.idealworks.com/en/robotics/iw-hub](https://www.idealworks.com/en/robotics/iw-hub)

#### 타 기종과의 비교

![스크린샷 2026-08-26 174345.png](image6.png)

#### 선정 근거

1. 반송 + 피킹(다중 토트 랙을 얹는 형태) 작업을 수행하고, 기존 물류 현장에서 바로 사용 가능해야 함. 
    
    → Geekplus 등의 시장 점유율 상위 모델들은 대대적인 물류 자동화 환경부터 구축해야 함.
    
2. VDA5050 프로토콜을 사용하는 제어 방식임. 즉, 이미 FMS와의 통신이 규격화된 상태.
    
    → 이는 이후 AMR 모델 교체 시에도 FMS와의 통신 포맷이 일정하므로 모듈식 교체가 가능.
    
3. BMW-NVIDIA 디지털 트윈 협업을 위해 이미 제조사의 공식 에셋으로 Isaac Sim에서 사용 가능.