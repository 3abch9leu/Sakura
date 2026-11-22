import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PlantComponent } from './plant.component';

describe('PlantComponent', () => {
  let component: PlantComponent;
  let fixture: ComponentFixture<PlantComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PlantComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(PlantComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
